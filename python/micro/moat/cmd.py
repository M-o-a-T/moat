from .compat import Event,ticks_ms,ticks_add,ticks_diff,wait_for_ms,print_exc,CancelledError,TaskGroup, idle
from .proto import _Stacked
from contextlib import asynccontextmanager

from serialpacker import SerialPacker
from msgpack import Packer,Unpacker, OutOfData
from pprint import pformat

import uasyncio
from uasyncio import core
from uasyncio import Lock
from uasyncio.stream import Stream

import logging
logger = logging.getLogger(__name__)

#
# Basic infrastructure to run an RPC system via an unreliable,
# possibly-reordering, and/or stream-based transport
#
# We have a stack of classes, linked by parent/child pointers.
# At the bottom there's some Stream thing, at the top we have the command
# handling, implemented by the classes Request (send a command, wait for
# reply) and Base (receive a command, generate a reply).
#
# Everything is fully asynchronous. Each class has a "run" method which is
# required to call its child's "run", as well as do internal housekeeping
# if required. A "run" method may expect its parent to be operational;
# it gets cancelled if/when that is no longer true. When a child "run"
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
    # modules on top of each other; the first is the final two are a
    # Request and a Base.
    #

    async def run(self):
        await idle()

    async def dispatch(self, action, msg):
        p = None
        if isinstance(action,str) and len(action) > 1:
            try:
                p = getattr(self,"cmd_"+action)
            except AttributeError:
                # retry with single character
                pass
            else:
                action=""
        if p is None:
            if not action:
                p = self.cmd
            else:
                # may raise AttributeError
                p = getattr(self,"cmd_"+action[0])
                action = action[1:]

        if p is None:
            raise AttributeError(action)

        if isinstance(msg,dict):
            return await p(action, **msg)
        else:
            return await p(action, msg)


class Request(_Stacked):
    # Request/Response handler (client side)
    # 
    # Call "send" with an action (a string or list) to select
    # the function of the recipient. The response is returned / raised.
    # The second argument is expanded by the recipient if it is a dict.
    # Requests are cancelled when the lower layer terminates.
    # 
    # The transport must be reliable.

    async def _init(self):
        await super()._init()
        self.reply = {}
        self.seq = 0

    async def _run(self):
        try:
            async with TaskGroup() as tg:
                self._tg = tg
                while True:
                    msg = await self.parent.recv()
                    await self.dispactch(msg)
        finally:
            for k,e in self.reply.items():
                if isinstance(e,Event):
                    self.reply[k] = CancelledError()
                    e.set()


    async def _handle_request(a,i,d,msg):
        try:
            res = await self.child.dispatch(a,d)
        except Exception as exc:
            print("ERROR handling",a,i,d,msg, file=sys.stderr)
            print_exc(exc)
            if i is None:
                return
            res = {'e':str(exc),'i':i}
        else:
            if i is None:
                return
            res = {'d':res,'i':i}
        await self.parent.send(res)


    async def dispatch(self, msg):
        if not isinstance(msg,dict):
            print("?",msg)
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
                print("?",d,msg)
                return

            e = msg.pop("e",None) if d is None else None
            try:
                evt = self.reply.pop(i)
            except KeyError:
                print("?",i,msg)
                return # errored?
            if isinstance(evt,Event):
                self.reply[i] = d if e is None else RemoteError(e)
                evt.set()
            else: # duh. Recorded error? put it back
                self.reply[i] = evt

    async def send(self, action, msg):
        # queue a request
        self.seq += 1
        seq = self.seq
        msg = {"a":action,"d":msg,"i":seq}

        e = Event()
        self.reply[seq] = e
        try:
            await self.parent.send(msg)
            await e.wait()
            res = self.reply[seq]
        finally:
            del self.reply[seq]

        if isinstance(res,Exception):
            raise res
        return res

    async def send_nr(self, action, msg):
        # queue a message, doesn't expect a reply
        msg = {"a":action,"d":msg}
        await self.parent.send(msg)

    async def run(self):
        try:
            await self.child.run()
        finally:
            for k,e in self.reply.items():
                if isinstance(e,Event):
                    self.reply[k] = CancelledError()
                    e.set()

