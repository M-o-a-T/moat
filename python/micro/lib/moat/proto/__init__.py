from ..compat import TaskGroup

try:
    import anyio
except ImportError:
    class EndOfStream(Exception):
        pass
    class BrokenResourceError(Exception):
        pass
else:
    EndOfStream = anyio.EndOfStream
    BrokenResourceError = anyio.BrokenResourceError

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

class RemoteError(RuntimeError):
    pass

class ChannelClosed(RuntimeError):
    pass

class _NotGiven:
    pass

class NotImpl:
    def __init__(self, parent):
        self.parent = parent

    async def dispatch(self,*a):
        raise NotImplementedError(f"{self.parent} {repr(a)}")

    async def error(self, exc):
        raise RuntimeError()

    async def run(self):
        print("RUN of",self.__class__.__name__)
        pass

    async def start_sub(self, tg):
        pass

class _Stacked:
    def __init__(self, parent, *a,**k):
        self.parent = parent
        self.child = NotImpl(self)

    def stack(self, cls, *a, **k):
        sup = cls(self, *a,**k)
        self.child = sup
        return sup

    async def error(self, exc):
        await self.child.error(exc)

    async def run(self):
        r = getattr(self, "_run", None)
        if r is None:
            return await self.child.run()
        async with TaskGroup() as tg:
            runner = await tg.spawn(r)
            await self.child.run()
            runner.cancel()

    async def send(self, *a, **k):
        return await self.parent.send(*a, **k)

    async def recv(self, *a, **k):
        return await self.parent.recv(*a, **k)

    async def dispatch(self, *a, **k):
        return await self.child.dispatch(*a, **k)


class Logger(_Stacked):
    def __init__(self, parent, txt="S", **k):
        super().__init__(parent, **k)
        self.txt = txt
        from pprint import pformat
        self._pformat = pformat

    async def run(self):
        print(f"X:{self.txt} start")
        try:
            await super().run()
        except EndOfStream:
            print(f"X:{self.txt} stop EOF")
            raise
        except BrokenResourceError:
            print(f"X:{self.txt} stop DIED")
            raise
        except Exception as exc:
            print(f"X:{self.txt} stop {repr(exc)}")
            raise
        else:
            print(f"X:{self.txt} stop")

    async def send(self,a,m=None):
        if m is None:
            m=a
            a=None

        if isinstance(m,dict):
            mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        else:
            mm=repr(m)
        if a is None:
            print(f"S:{self.txt} {mm}")
            await self.parent.send(m)
        else:
            print(f"S:{self.txt} {a} {mm}")
            await self.parent.send(a,m)

    async def dispatch(self,a,m=None):
        if m is None:
            m=a
            a=None

        mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        if a is None:
            print(f"D:{self.txt} {mm}")
            await self.child.dispatch(m)
        else:
            print(f"D:{self.txt} {a} {mm}")
            await self.child.dispatch(a,m)
        print(f"{self.txt}:\n{self._pformat(vars(self.child))}")

    async def recv(self):
        msg = await self.parent.recv()
        if isinstance(msg,dict):
            mm=" ".join(f"{k}={repr(v)}" for k,v in msg.items())
        else:
            mm=msg
        print(f"R:{self.txt} {mm}")
        return msg

