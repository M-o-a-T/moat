# *********************************
# * WARNING *  READ AFTER EDITING *
# *********************************
#
# This file should be synced with moat/proto/__init__.py
# except for using print() instead of logging
# and not understanding anyio's exceptions.

"""
This class implements the basic infrastructure to run an RPC system via an
unreliable, possibly-reordering, and/or stream-based transport

We have a stack of classes, linked by parent/child pointers.
The parent chain leads to the actual hardware, represented by some Stream
subclass.

The child chain leads to the subcommand handler responsible for this RPC
connection, which forwards the incoming command to the system's main
command handler.

Everything is fully asynchronous. Each class has a "run" method which is
required to call its child's "run", as well as do internal housekeeping
if required. A "run" method may expect its parent to be operational;
it gets cancelled if/when that is no longer true. When a child "run"
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

from ..compat import TaskGroup


class RemoteError(RuntimeError):
    pass


class SilentRemoteError(RemoteError):
    pass


class ChannelClosed(RuntimeError):
    pass


class _Stacked:
    """
    A no-op stack module. Override me to implement interesting features.

    If you need a separate task, implement a 'run(evt)' method.
    You *must* call `evt.set` when the connection is up.
    """
    def __init__(self, parent):
        self.parent = parent
        self.child = None

    def stack(self, cls, *a, **k):
        """
        Add (and return) a child module.
        """
        self.child = sup = cls(self, *a, **k)
        return sup

    def error(self, exc):
        """
        An error has been detected on the hardware side.

        Forwarded to the top by default.
        """
        self.child.error(exc)

    async def _run(self, evt):
        """
        Main code. Starts ".run" if that exists.
        """
        r = getattr(self, "run", None)
        if r is None:
            return await self.parent._run(evt)
        async with TaskGroup() as tg:
            par = Event()
            runner = await tg.spawn(self.parent._run, par, _name="run_s")
            await par.wait()
            await r(evt)
            runner.cancel()

    async def send(self, *a, **k):
        return await self.parent.send(*a, **k)

    async def recv(self, *a, **k):
        return await self.parent.recv(*a, **k)


class Logger(_Stacked):
    """
    Log whatever messages cross this stack.
    """
    def __init__(self, parent, txt="S", **k):
        super().__init__(parent, **k)
        self.txt = txt

    async def _run(self):
        print(f"X:{self.txt} start", file=sys.stderr)
        try:
            await super()._run()
        except Exception as exc:
            print(f"X:{self.txt} stop {repr(exc)}", file=sys.stderr)
            raise
        else:
            print(f"X:{self.txt} stop", file=sys.stderr)

    def error(self, exc):
        print(f"X:{self.txt} err {repr(exc)}", file=sys.stderr)
        self.child.error(exc)

    async def send(self, a, m=None):
        if m is None:
            m = a
            a = None

        if isinstance(m, dict):
            mm = " ".join(f"{k}={repr(v)}" for k, v in m.items())
        else:
            mm = repr(m)
        if a is None:
            print(f"S:{self.txt} {mm}", file=sys.stderr)
            await self.parent.send(m)
        else:
            print(f"S:{self.txt} {a} {mm}", file=sys.stderr)
            await self.parent.send(a, m)

    async def recv(self):
        msg = await self.parent.recv()
        if isinstance(msg, dict):
            mm = " ".join(f"{k}={repr(v)}" for k, v in msg.items())
        else:
            mm = msg
        print(f"R:{self.txt} {mm}", file=sys.stderr)
        return msg

