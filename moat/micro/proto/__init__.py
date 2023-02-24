# *********************************
# * WARNING *  READ AFTER EDITING *
# *********************************
#
# This file should be synced with micro/lib/moat/proto/__init__.py
# except for using logging instead of print().

from ..compat import TaskGroup

import logging
logger = logging.getLogger(__name__)

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

class SilentRemoteError(RemoteError):
    pass

class ChannelClosed(RuntimeError):
    pass

class NotImpl:
    def __init__(self, parent):
        self.parent = parent

    async def dispatch(self,*a):
        raise NotImplementedError(f"{self.parent} {repr(a)}")

    async def error(self, exc):
        raise RuntimeError()

    async def run(self):
        logger.debug("RUN of %s",self.__class__.__name__)
        pass

    async def run_sub(self):
        pass

class _Stacked:
    def __init__(self, parent):
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

    async def aclose(self):
        pass


class Logger(_Stacked):
    def __init__(self, parent, txt="S", **k):
        super().__init__(parent, **k)
        self.txt = txt

    async def run(self):
        logger.debug("X:%s start", self.txt)
        try:
            await super().run()
        except EndOfStream:
            logger.debug("X:%s stop EOF", self.txt)
            raise
        except BrokenResourceError:
            logger.debug("X:%s stop DIED", self.txt)
            raise
        except Exception as exc:
            logger.debug("X:%s stop %r", self.txt, exc)
            raise
        else:
            logger.debug("X:%s stop", self.txt)

    async def send(self,a,m=None):
        if m is None:
            m=a
            a=None

        if isinstance(m,dict):
            mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        else:
            mm=repr(m)
        if a is None:
            logger.debug("S:%s %s", self.txt, mm)
            await self.parent.send(m)
        else:
            logger.debug("S:%s %s %s", self.txt,a,mm)
            await self.parent.send(a,m)

    async def dispatch(self,a,m=None):
        if m is None:
            m=a
            a=None

        mm=" ".join(f"{k}={repr(v)}" for k,v in m.items())
        if a is None:
            logger.debug("D:%s %s", self.txt, mm)
            await self.child.dispatch(m)
        else:
            logger.debug("D:%s %s %s", self.txt, a, mm)
            await self.child.dispatch(a,m)
        logger.debug("%s:\n%r", self.txt,vars(self.child))

    async def recv(self):
        msg = await self.parent.recv()
        if isinstance(msg,dict):
            mm=" ".join(f"{k}={repr(v)}" for k,v in msg.items())
        else:
            mm=msg
        logger.debug("R:%s %s", self.txt,mm)
        return msg

