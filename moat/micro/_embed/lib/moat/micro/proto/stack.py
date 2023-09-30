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

from __future__ import annotations

import sys

from contextlib import asynccontextmanager

from moat.micro.compat import TaskGroup, log
from moat.util import as_proxy, CtxObj


@as_proxy("_rErr", replace=True)
class RemoteError(RuntimeError):
    pass


@as_proxy("_rErrS", replace=True)
class SilentRemoteError(RemoteError):
    pass


@as_proxy("_rErrCCl", replace=True)
class ChannelClosed(RuntimeError):
    pass

class _BaseAny(CtxObj):
    """
    A stream base module.
    """
    s = None

    def __init__(self):
        pass

    @asynccontextmanager
    async def _ctx(self):
        raise NotImplementedError("'_ctx' in "+self.__class__.__name__)
        yield None

    @asynccontextmanager
    async def setup(self):
        raise NotImplementedError("'setup' in "+self.__class__.__name__)
        yield None


class BaseMsg(_BaseAny):
    """
    A stream base module for messages. May not be useful.

    Implement @_ctx and send/recv.
    """
    async def send(self, m:Any) -> Any:
        raise NotImplementedError("'send' in "+self.__class__.__name__)

    async def recv(self) -> Any:
        raise NotImplementedError("'recv' in "+self.__class__.__name__)

class BaseBlk(_BaseAny):
    """
    A stream base module for bytestrings. May not be useful.

    Implement @_ctx and snd/rcv.
    """
    async def snd(self, m:Any) -> Any:
        raise NotImplementedError("'send' in "+self.__class__.__name__)

    async def rcv(self) -> Any:
        raise NotImplementedError("'recv' in "+self.__class__.__name__)

class BaseBuf(_BaseAny):
    """
    A stream base module for bytestreams.

    Implement @_ctx and rd/wr.
    """
    async def rd(self, buf) -> int:
        raise NotImplementedError("'rd' in "+self.__class__.__name__)

    async def wr(self, buf) -> int:
        raise NotImplementedError("'wr' in "+self.__class__.__name__)


class _StackedAny(CtxObj):

    def __init__(self, parent):
        self.parent = parent

    async def setup(par):
        breakpoint()
        pass

    @asynccontextmanager
    async def _ctx(self):
        """
        Open a context. By default, simply forwards to the parent.
        """
        async with self.parent.conn() as par:
            await self.setup(par)
            self.par = par
            try:
                yield self
            finally:
                await self.teardown(par)
                self.par = None


class StackedMsg(BaseMsg):
    """
    A no-op stack module for messages. Override me to implement interesting features.

    Override the "_ctx" async context manager to do interesting things.
    
    Use "par" to store the parent's context.
    """
    par = None
    parent = None

    __init__ = _StackedAny.__init__
    _ctx = _StackedAny._ctx

    async def send(self, m):
        "Send. Transmits a structured message"
        return await self.par.send(m)

    async def recv(self):
        "Receive. Returns a message."
        return await self.par.recv(*a)

    async def cwr(self, buf):
        "Console Send. Returns when the buffer is transmitted."
        await self.par.cwr(buf)

    async def crd(self, buf) -> len:
        "Console Receive. Returns data by reading into a buffer."
        return await self.par.crd(buf)

class StackedBuf(BaseBuf):
    """
    A no-op stack module for byte steams. Override me to implement interesting features.

    Override the "_ctx" async context manager to do interesting things.
    
    Use "par" instead of "parent" for the parent's context.
    """
    par = None
    parent = None

    __init__ = _StackedAny.__init__
    _ctx = _StackedAny._ctx

    async def wr(self, buf):
        "Send. Returns when the buffer is transmitted."
        await self.par.wr(buf)

    async def rd(self, buf) -> len:
        "Receive. Returns data by reading into a buffer."
        return await self.par.rd(buf)


class StackedBlk(BaseBlk):
    """
    A no-op stack module for bytestrings. Override me to implement interesting features.

    Override the "_ctx" async context manager to do interesting things.
    
    Use "par" instead of "parent" for the parent's context.
    """
    par = None
    parent = None

    __init__ = _StackedAny.__init__
    _ctx = _StackedAny._ctx
    cwr = StackedMsg.cwr
    crd = StackedMsg.crd

    async def snd(self, m):
        "Send. Transmits a structured message"
        return await self.par.send(m)

    async def rcv(self):
        "Receive. Returns a message."
        return await self.par.recv(*a)


class LogMsg:
    """
    Log whatever messages cross this stack.

    This implements all of StackedMsg/Buf/Blk.
    """
    def __init__(self, parent, txt="S", **k):
        super().__init__(parent, **k)
        self.txt = txt

    @asynccontextmanager
    async def _ctx(self):
        log("X:%s start", self.txt)
        try:
            async with self.parent as self.par:
                yield self
        except BaseException as exc:
            log("X:%s stop %r", self.txt, exc)
            raise
        else:
            log("X:%s stop", self.txt)
        finally:
            self.par = None

    def _repr(self, m, sub=None):
        if not isinstance(m,dict):
            return repr(m)
        res = []
        for k,v in m.items():
            if sub == k:
                res.append(f"{k}={self._repr(v)}")
            else:
                res.append(f"{k}={v}")
        return "{" + " ".join(res) + "}"

    async def send(self, m):
        "Send message."
        mm = self._repr(m)
        log("S:%s %s", self.txt, self._repr(m,'d'))
        try:
            res = await self.par.send(m)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%s", self.txt, self._repr(res,'d'))
            return res

    async def recv(self):
        "Recv message."
        log("R:%s", self.txt)
        try:
            msg = await self.par.recv()
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %s", self.txt, self._repr(msg,'d'))
            return msg

    async def snd(self, m):
        "Send buffer."
        log("S:%s %r", self.txt, m)
        try:
            res = await self.par.snd(m)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise

    async def rcv(self):
        "Recv buffer."
        log("R:%s", self.txt)
        try:
            msg = await self.par.rcv()
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %r", self.txt, msg)
            return msg

    async def wr(self, buf):
        "Send buf."
        log("S:%s %r", self.txt, buf)
        try:
            res = await self.par.wr(buf)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%r", self.txt, res)
            return res

    async def rd(self, buf) -> len:
        "Receive buf."
        log("R:%s %d", self.txt, len(buf))
        try:
            res = await self.par.rd(buf)
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %r", self.txt, repr(buf[:res]))
            return res

LogBuf = LogMsg
LogBlk = LogMsg
