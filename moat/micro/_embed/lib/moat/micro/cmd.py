"""
Basic infrastructure to run an RPC system via an unreliable,
possibly-reordering, and/or stream-based transport

We have a stack of classes, linked by parent/child pointers.
At the bottom there's some Stream adapter. At the top we have the command
handling, implemented by the classes Request (send a command, wait for
reply) and Base (receive a command, generate a reply). Base classes form
a tree.

Everything is fully asynchronous. Each class has a "run" method which is
required to call its child's "run", as well as do internal housekeeping
if required. A "run" method may expect its parent to be operational;
it gets cancelled if/when that is no longer true. When a child's "run"
terminates, the parent's "run" needs to return.

Incoming messages are handled by the child's "dispatch" method. They
are expected to be fully asynchronous, i.e. a "run" method that calls
"dispatch" must use a separate task to do so.

Outgoing messages are handled by the parent's "send" method. Send calls
return when the data has been sent, implying that sending on an
unreliable transport will wait for the message to be confirmed. Sending
may fail.
"""


import sys

from moat.util import (  # pylint: disable=no-name-in-module
    Queue,
    ValueEvent,
    as_proxy,
    attrdict,
    import_,
    obj2name,
)

from moat.micro.compat import CancelledError, TaskGroup, WouldBlock, idle, print_exc, Event, wait_for_ms
from moat.micro.proto.stack import RemoteError, SilentRemoteError, _Stacked

as_proxy("_KyErr", KeyError, replace=True)
as_proxy("_AtErr", AttributeError, replace=True)
as_proxy("_NiErr", NotImplementedError, replace=True)


class BaseCmd:
    """
    Request/response handler

    This object dispatches commands.

    Incoming requests call `cmd` if the action is empty. Otherwise, if the
    action is a string, the complete string is tried first, then the first
    character. Otherwise (action is a list) the first element is used
    as-is.

    If the action is empty, call the `cmd` method instead. Otherwise if
    no method is found return an error.

    The `send` method simply forwards to the root, for convenience.

    This is the toplevel entry point. You build a request stack by piling
    modules on top of each other; the final one is a Request. On top of
    that Request you stack Base subclasses according to the functions you
    need.
    """

    _tg: TaskGroup = None

    def __init__(self, root, cfg):
        self._sub = {}
        self.cfg = cfg
        self.root = root
        self._t = None
        self._ready = Event()

    async def run(self):
        """
        Main loop for this part of your code.

        By default, does nothing except setting the ``_ready`` event.
        """
        self._ready.set()

    async def _run(self):
        """
        Runs my (and my children's) "run" methods.
        """
        async with TaskGroup() as tg:
            self._tg = tg
            self._t = await tg.spawn(self.run, _name="run")
            await self._start()

    async def _start(self):
        for k,v in self._sub.items():
            if isinstance(v, BaseCmd):
                v.__t = await self._tg.spawn(v._run, _name="sub:" + k)

    async def restart(self):
        """
        Tell this module to restart itself.

        This module's taskgroup persists. The module's runner and all
        submodules are cancelled and restarted.
        """
        for k,v in self._sub.items():
            v.__t.cancel()
        self._t.cancel()
        self._t = await tg.spawn(self.run, _name="run")
        await self._start()

    async def attach(self, name, cmd, *a, **kw):
        """
        Attach a named command handler to me and run it.
        """
        self.detach(name)
        self._sub[name] = cmd
        cmd.__t = await self._tg.spawn(cmd._run, *a, _name="sub:" + name, **kw)

    def detach(self, name):
        """
        Detach a named command handler from me and kill its task.
        """
        try:
            cmd = self._sub.pop(name)
        except KeyError:
            return
        try:
            cmd.__t.cancel()
        except AttributeError:
            pass
        else:
            del cmd.__t

    async def dispatch(
            self, action: str | list[str], msg: dict, wait:bool = True,
    ):  # pylint:disable=arguments-differ
        """
        Process one incoming message.

        @msg is either a dict (keyword+value for the destination handler)
        or not (single direct argument).

        @action may be a string or an array. The first element of
        the array is used to look up a submodule. Same for the first char
        of a string, if there's no command with that name. An empty-string
        action calls the ``cmd`` method.

        Returns whatever the called command returns/raises, or raises
        AttributeError if no command is found.
        """

        async def c(p):
            if isinstance(msg, dict):
                r = p(**msg)
            else:
                r = p(msg)
            if hasattr(r, "throw"):  # coroutine
                r = await r
            return r

        if not action:
            # pylint: disable=no-member
            await self._ready.wait()
            return await c(self.cmd)
            # if there's no "self.cmd", the resulting AttributeError is our reply

        if not isinstance(action, str) and len(action) == 1:
            action = action[0]
        if isinstance(action, str):
            try:
                p = getattr(self, "cmd_" + action)
            except AttributeError:
                pass
            else:
                await self._ready.wait()
                return await c(p)

        try:
            sub = self._sub[action[0]]
        except KeyError:
            raise AttributeError(action) from None
        else:
            return await sub.dispatch(action[1:], msg, wait=wait)

    def cmd__dir(self):
        """
        Rudimentary introspection. Returns a list of available commands @c and
        submodules @d. j=True if callable directly.
        """
        c = []
        d = list(self._sub.keys())
        res = dict(c=c, d=d)

        for k in dir(self):
            if k.startswith("cmd_") and k[4] != '_':
                c.append(k[4:])
            elif k == "cmd":
                res['j'] = True
        return res


class StreamCmd(_Stacked):
    """
    This is a command handler that packages requests and sends them onto a
    channel.

    It is both a BaseCmd and a _Stacked. Because MicroPython doesn't support
    multiple inheritance we duck-type the BaseCmd part.
    """

    def __init__(self, root, cfg):
        # called as a BaseCmd
        BaseCmd.__init__(self, root, cfg)
        self.reply = {}
        self.seq = 0
        self._ready = Event()

    async def run(self):
        """
        Start the stack
        """
        top = await self.setup()
        self.parent = top
        top.child = self
        await self._tg.spawn(top._run, self._ready)
        try:
            while True:
                msg = await self.parent.recv()
                await self._handle(msg)
        finally:
            self._cleanup_open_commands()
            top.child = None
            self.parent = None

    # stacked
    async def error(self, exc):
        print("ERROR: " + repr(error), file=sys.stderr)

    async def send(self,*a,**k):
        raise RuntimeError("Should not be called")

    async def recv(self,*a,**k):
        raise RuntimeError("Should not be called")

    async def setup(self):
        """Setup my stack. Returns the stack's top module. Must be overridden."""
        raise NotImplementedError("Override me! "+self.__class__.__name__)

    def _cleanup_open_commands(self):
        for e in self.reply.values():
            e.set_error(CancelledError())

    async def _handle_request(self, a, i, d, msg):
        """
        Handler for a single request.

        `_handle` starts this in a new task for each message.
        """
        res = {'i': i}
        try:
            r = await self.root.dispatch(a, d)
        except SilentRemoteError as exc:
            if i is None:
                return
            res["e"] = exc
        except WouldBlock:
            raise
        except Exception as exc:  # pylint:disable=broad-exception-caught
            # TODO only when debugging
            print("ERROR handling", a, i, d, msg, file=sys.stderr)
            print_exc(exc)
            if i is None:
                return
            try:
                obj2name(type(exc))
            except KeyError:
                res["e"] = "E:" + repr(exc)
            else:
                res["e"] = exc
        else:
            if i is None:
                return
            res["d"] = r
        try:
            await self.parent.send(res)
        except TypeError as exc:
            print("ERROR returning", res, file=sys.stderr)
            print_exc(exc)
            res = {'e': "T:" + repr(exc), 'i': i}
            await self.parent.send(res)

    async def _handle(self, msg):
        """
        Main handler for incoming messages
        """
        if not isinstance(msg, dict):
            print("?3", msg, file=sys.stderr)
            return
        a = msg.pop("a", None)
        i = msg.pop("i", None)
        d = msg.pop("d", None)

        if a is not None:
            # incoming request
            # runs in a separate task
            # TODO create a task pool?
            await self._tg.spawn(self._handle_request, a, i, d, msg, _name="hdl:" + str(a))

        else:
            # reply
            if i is None:
                # No seq#. Dunno what to do about these.
                print("?4", d, msg, file=sys.stderr)
                return

            e = msg.pop("e", None) if d is None else None
            try:
                evt = self.reply[i]
            except KeyError:
                print("?5", i, msg, file=sys.stderr)
                return  # errored?
            if evt.is_set():
                print("Duplicate reply?", a, i, d, msg, file=sys.stderr)
                return  # duplicate??
            if e is None:
                evt.set(d)
            elif isinstance(e, Exception):
                evt.set_error(e)
            else:
                evt.set_error(RemoteError(e, d))

    async def dispatch(self, action, msg=None, wait=True):  # pylint:disable=arguments-differ
        """
        Forward a request to the remote side, return the response.

        The message is either the second parameter, or a dict (use any
        number of keywords).

        If @wait is False, the message doesn't have a sequence number and
        thus no reply will be expected.
        """

        if not wait:
            msg = {"a": action, "d": msg}
            await self.parent.send(msg)
            return

        # Find a small-ish but unique seqnum
        if self.seq > 10 * (len(self.reply) + 5):
            self.seq = 9
        while True:
            self.seq += 1
            seq = self.seq
            if seq not in self.reply:
                break
        msg = {"a": action, "d": msg, "i": seq}

        self.reply[seq] = e = ValueEvent()
        try:
            await self.parent.send(msg)
            return await e.get()
        finally:
            del self.reply[seq]


class Dispatch(BaseCmd):
    """
    This is the system's root dispatcher.

    Call "send" with an action (a string or list) and either a single
    parameter or some key/value data. The response is returned / raised.

    @ready is an Event that'll be set when the system is up.
    """

    APP = "app"
    _tg: TaskGroup = None
    _ready: Event = None

    def __init__(self, cfg:dict=None):
        self._ready = Event()
        self.apps = {}
        super().__init__(self, cfg)

    async def _run(self):
        raise RuntimeError("don't call")

    async def run(self):
        """
        Runs the stack.
        """
        async with TaskGroup() as self._tg:
            await self._setup_apps()

    async def wait_ready(self):
        "delay until ready"
        if self._ready is not None:
            await self._ready.wait()

    async def update_config(self):
        "called after the config has been updated"
        if self.APP is not None:
            await self._setup_apps()

    async def _setup_apps(self):
        # TODO send errors back
        if self.APP is None:
            return
        gcfg = self.cfg
        apps = gcfg.get("apps", {})
        tg = self._tg

        def imp(name):
            return import_(f"{self.APP}.{name}", 1)

        for name in list(self.apps.keys()):
            if name not in apps:
                app = self.apps[name]
                self.detach(app)  # pylint: disable=protected-access
                sys.modules.pop(app.__module__, None)

        # First setup the app data structures
        for name, v in apps.items():
            if name in self.apps:
                continue

            cfg = getattr(gcfg, name, {})
            cmd = imp(v)(self, cfg)
            self.apps[name] = cmd
            self._sub[name] = cmd

        # Second, run them all.
        # For existing apps, tell it to update its configuration.
        for name, app in self.apps.items():
            if hasattr(app, "_req_scope"):
                cfg = getattr(gcfg, name, attrdict())
                await app.config_updated(cfg)
            else:
                app._req_scope = await tg.spawn(  # pylint: disable=protected-access
                    app.run, _name="mp_app_" + name
                )

        # Third, wait for them to be up.
        for k,v in self.apps.items():
            try:
                await wait_for_ms(250, v._ready.wait)
            except TimeoutError:
                print(f"* Waiting for App:{k}", file=sys.stderr)
                await v._ready.wait()

        if self._ready is not None:
            print("* Running", file=sys.stderr)
            self._ready.set()


    async def send(self, action, _msg=None, **kw):  # pylint:disable=arguments-differ
        if _msg is None:
            _msg = kw
        elif kw:
            raise TypeError("cannot use both msg data and keywords")
        return await self.dispatch(action, _msg)

    async def send_nr(self, action, _msg=None, **kw):  # pylint:disable=arguments-differ
        if _msg is None:
            _msg = kw
        elif kw:
            raise TypeError("cannot use both msg data and keywords")
        return await self.dispatch(action, _msg, wait=False)
        # XXX run in a detached task


