from .compat import Event,ticks_ms,ticks_add,ticks_diff,wait_for_ms,print_exc,CancelledError,TaskGroup, idle, ValueEvent
from .proto import _Stacked, RemoteError, SilentRemoteError as FSError
from contextlib import asynccontextmanager

from serialpacker import SerialPacker

import sys

#
# Basic infrastructure to run an RPC system via an unreliable,
# possibly-reordering, and/or stream-based transport
#
# We have a stack of classes, linked by parent/child pointers.
# At the bottom there's some Stream adapter. At the top we have the command
# handling, implemented by the classes Request (send a command, wait for
# reply) and Base (receive a command, generate a reply). Base classes form
# a tree.
#
# Everything is fully asynchronous. Each class has a "run" method which is
# required to call its child's "run", as well as do internal housekeeping
# if required. A "run" method may expect its parent to be operational;
# it gets cancelled if/when that is no longer true. When a child's "run"
# terminates, the parent's "run" needs to return.
#
# Incoming messages are handled by the child's "dispatch" method. They
# are expected to be fully asynchronous, i.e. a "run" method that calls
# "dispatch" must use a separate task to do so.
#
# Outgoing messages are handled by the parent's "send" method. Send calls
# return when the data has been sent, implying that sending on an
# unreliable transport will wait for the message to be confirmed. Sending
# may fail.


class BaseCmd(_Stacked):
    # Request/response handler (server side)
    # 
    # This is attached as a child to the Request object.
    #
    # Incoming requests call `cmd_*` with `*` being the action. If the
    # action is a string, the complete string is tried first, then
    # the first character. Otherwise (action is a list) the first
    # element is used as-is.
    #
    # If the action is empty, call the `cmd` method instead. Otherwise if
    # no method is found return an error.
    # 
    # Attach a sub-base directly to their parents by setting their
    # `cmd_XX` property to it.
    #
    # The `send` method simply forwards to its parent, for convenience.
    #
    # This is the toplevel entry point. You build a request stack by piling
    # modules on top of each other; the final one is a Request. On top of
    # that Request you stack Base subclasses according to the functions you
    # need.
    #

    async def run(self):
        pass

    async def start_sub(self,tg):
        # start my (and my children's) "run" task
        await tg.spawn(self.run)

        for k in dir(self):
            if not k.startswith('dis_'):
                continue
            v = getattr(self,k)
            if isinstance(v, BaseCmd):
                await v.start_sub(tg)


    async def dispatch(self, action, msg):
        async def c(p):
            if isinstance(msg,dict):
                r = p(**msg)
            else:
                r = p(msg)
            if hasattr(r,"throw"):  # coroutine
                r = await r
            return r

        if not action:
            return await c(self.cmd)
            # if there's no "self.cmd", the resulting AttributeError is our reply

        if isinstance(action,str) and len(action) > 1:
            try:
                p = getattr(self,"cmd_"+action)
            except AttributeError:
                pass
            else:
                return await c(p)

        if len(action) > 1:
            try:
                dis = getattr(self,"dis_"+action[0])
            except AttributeError:
                raise AttributeError(action)
            else:
                return await dis(action[1:], msg)
        else:
            return await c(getattr(self,"cmd_"+action[0]))

    async def __call__(self, *a, **k):
        return await self.dispatch(*a, **k)

    async def config_updated(self):
        for k in dir(self):
            if k.startswith("dis_"):
                v = getattr(self,k)
                await v.config_updated()

    def cmd__dir(self):
        # rudimentary introspection
        d=[]
        c=[]
        res = dict(c=c, d=d)
        for k in dir(self):
            if k.startswith("cmd_") and k[4] != '_':
                c.append(k[4:])
            elif k.startswith("dis_") and k[4] != '_':
                d.append(k[4:])
            elif k == "cmd":
                res['j'] = True
        return res

    @property
    def request(self):
        return self.parent.request

    @property
    def base(self):
        return self.parent.base


class ClientBaseCmd(BaseCmd):
    # a BaseCmd subclass that adds link state tracking
    def __init__(self, parent):
        super().__init__(parent)
        self.started = Event()

    def cmd_link(self, s=None):
        self.started.set()

    async def wait_start(self):
        await self.started.wait()


class Request(_Stacked):
    # Request/Response handler (client side)
    # 
    # Call "send" with an action (a string or list) to select
    # the function of the recipient. The response is returned / raised.
    # The second argument is expanded by the recipient if it is a dict.
    # Requests are cancelled when the lower layer terminates.
    # 
    # The transport must be reliable.

    def __init__(self, *a, **k):
        super().__init__(*a,**k)
        self.reply = {}
        self.seq = 0

    @property
    def request(self):
        return self

    @property
    def base(self):
        return self.child

    def terminate(self):
        self._tg.cancel()

    async def run(self):
        try:
            async with TaskGroup() as tg:
                self._tg = tg
                await self.child.start_sub(tg)

                while True:
                    msg = await self.parent.recv()
                    await self.dispatch(msg)
        finally:
            self._cleanup_open_commands()

    def _cleanup_open_commands(self):
        for e in self.reply.values():
            e.set_error(CancelledError())

    async def _handle_request(self, a,i,d,msg):
        res={'i':i}
        try:
            r = await self.child.dispatch(a,d)
        except FSError as exc:
            res["e"] = exc.args[0]
        except Exception as exc:
            print("ERROR handling",a,i,d,msg, file=sys.stderr)
            print_exc(exc)
            if i is None:
                return
            res["e"] = exc.args[0] if isinstance(exc, RemoteError) else repr(exc)
        else:
            if i is None:
                return
            res["d"] = r
        try:
            await self.parent.send(res)
        except TypeError as exc:
            print("ERROR returning",res, file=sys.stderr)
            print_exc(exc)
            res = {'e':repr(exc),'i':i}
            await self.parent.send(res)


    async def dispatch(self, msg):
        if not isinstance(msg,dict):
            print("?3",msg)
            return
        a = msg.pop("a",None)
        i = msg.pop("i",None)
        d = msg.pop("d",None)

        if a is not None:
            # request from the other side
            # runs in a separate task
            # TODO create a task pool
            await self._tg.spawn(self._handle_request,a,i,d,msg)

        else: # reply
            if i is None:
                # No seq#. Dunno what to do about these.
                print("?4",d,msg)
                return

            e = msg.pop("e",None) if d is None else None
            try:
                evt = self.reply[i]
            except KeyError:
                print("?5",i,msg)
                return # errored?
            if evt.is_set():
                print("Duplicate reply?",a,i,d,msg)
                return  # duplicate??
            if e is None:
                evt.set(d)
            else:
                evt.set_error(RemoteError(e))

    async def send(self, action, msg=None, **kw):
        # send a request, return the response
        if self.seq > 100 and not self.reply:
            self.seq = 9
        self.seq += 1
        seq = self.seq
        if msg is None:
            msg = kw
        elif kw:
            raise TypeError("cannot use both msg data and keywords")
        msg = {"a":action,"d":msg,"i":seq}

        e = ValueEvent()
        self.reply[seq] = e
        try:
            await self.parent.send(msg)
            return await e.get()
        finally:
            del self.reply[seq]

    async def send_nr(self, action, msg=None, **kw):
        # send a message, no reply
        if msg is None:
            msg = kw
        elif kw:
            raise TypeError("cannot use both msg data and keywords")
        msg = {"a":action,"d":msg}
        await self.parent.send(msg)

