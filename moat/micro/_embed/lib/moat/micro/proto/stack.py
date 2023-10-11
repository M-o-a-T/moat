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

from moat.micro.compat import TaskGroup, log, ACM, AC_use, AC_exit
from moat.util import as_proxy


@as_proxy("_rErr")
class RemoteError(RuntimeError):
    pass


@as_proxy("_rErrS")
class SilentRemoteError(RemoteError):
    pass


@as_proxy("_rErrCCl")
class ChannelClosed(RuntimeError):
    pass


class BaseConn:
    """
    The MoaT stream base class for "something connected that talks".

    This class *must* be used as an async context manager.

    Override `stream` to return the actual data link. Use `AC_use` to
    call an async context manager or to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.
    The default implementation of `setup` calls `stream` and stores the
    result in the attibute `s`.
    """
    s = None

    def __init__(self, cfg):
        self.cfg = cfg
        pass

    async def __aenter__(self):
        acm = ACM(self)
        await AC_use(self, self.teardown)
        await self.setup()
        return self

    async def __aexit__(self, *tb):
        self.s = None
        return await AC_exit(self, *tb)

    async def setup(self):
        """
        Object setup. Call the superclass!
        """
        pass

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """
        pass


    async def setup(self):
        await super().setup()
        self.s = await self.stream()

    async def stream(self):
        """
        Data stream setup.
        """
        raise NotImplementedError("'stream' in "+self.__class__.__name__)


class BaseMsg(BaseConn):
    """
    A stream base module for messages. May not be useful.

    Implement send/recv.
    """
    async def send(self, m:Any) -> Any:
        raise NotImplementedError("'send' in "+self.__class__.__name__)

    async def recv(self) -> Any:
        raise NotImplementedError("'recv' in "+self.__class__.__name__)

class BaseBlk(BaseConn):
    """
    A stream base module for bytestrings. May not be useful.

    Implement snd/rcv.
    """
    async def snd(self, m:Any) -> Any:
        raise NotImplementedError("'send' in "+self.__class__.__name__)

    async def rcv(self) -> Any:
        raise NotImplementedError("'recv' in "+self.__class__.__name__)

class BaseBuf(BaseConn):
    """
    A stream base module for bytestreams.

    Implement rd/wr.
    """
    async def rd(self, buf) -> int:
        raise NotImplementedError("'rd' in "+self.__class__.__name__)

    async def wr(self, buf) -> int:
        raise NotImplementedError("'wr' in "+self.__class__.__name__)


class StackedConn(BaseConn):
    """
    Base class for connection stacking.

    Connection stacks have a parent. `stream` generates a new
    connection from it, using its async context manager, and
    stores the result in the attribute ``par`.`
    """

    par = None
    parent = None

    def __init__(self, parent, cfg):
        super().__init__(cfg=cfg)
        self.parent = parent

    async def setup(self):
        """
        Start using this link.

        By default, calls `stream` with the parent object.
        """
        if self.par is not None:
            raise RuntimeError("Busy!")

        self.par = await self.stream(self.parent)

    async def teardown(self):
        """
        Stop using this link.
        """
        if self.par is None:
            raise RuntimeError("NotBusy!")

        self.par = None
        await super().teardown()

    async def stream(self, parent):
        """
        Use this parent.

        By default, simply enter its async context.
        """
        return await AC_use(self, parent)


class StackedMsg(StackedConn, BaseMsg):
    """
    A no-op stack module for messages. Override to implement interesting features.

    Use "par" to store the parent's context.
    """
    async def send(self, m):
        "Send. Transmits a structured message"
        return await self.par.send(m)

    async def recv(self):
        "Receive. Returns a message."
        return await self.par.recv()


    async def cwr(self, buf):
        "Console Send. Returns when the buffer is transmitted."
        await self.par.cwr(buf)

    async def crd(self, buf) -> len:
        "Console Receive. Returns data by reading into a buffer."
        return await self.par.crd(buf)


class StackedBuf(StackedConn, BaseBuf):
    """
    A no-op stack module for byte steams. Override to implement interesting features.

    Use "par" instead of "parent" for the parent's context.
    """
    async def wr(self, buf):
        "Send. Returns when the buffer is transmitted."
        await self.par.wr(buf)

    async def rd(self, buf) -> len:
        "Receive. Returns data by reading into a buffer."
        return await self.par.rd(buf)


class StackedBlk(StackedConn, BaseBlk):
    """
    A no-op stack module for bytestrings. Override to implement interesting features.

    Use "par" instead of "parent" for the parent's context.
    """
    cwr = StackedMsg.cwr
    crd = StackedMsg.crd

    async def snd(self, m):
        "Send. Transmits a structured message"
        return await self.par.send(m)

    async def rcv(self):
        "Receive. Returns a message."
        return await self.par.recv(*a)


class LogMsg(StackedMsg, StackedBuf, StackedBlk):
    """
    Log whatever messages cross this stack.

    This implements all of StackedMsg/Buf/Blk.
    """
    # StackedMsg is first because MicroPython uses only the first class and
    # we get `cwr` and `crd` that way.

    def __init__(self, parent, cfg):
        super().__init__(parent, cfg)
        self.txt = cfg.get("txt","S")

    async def setup(self):
        log("X:%s start", self.txt)
        await super().setup()

    async def teardown(self):
        log("X:%s stop", self.txt)
        await super().teardown()

    def _repr(self, m, sub=None):
        if not isinstance(m,dict):
            return repr(m)
        res = []
        for k,v in m.items():
            if sub == k:
                res.append(f"{k}={self._repr(v)}")
            else:
                res.append(f"{k}={repr(v)}")
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
        log("S:%s %r", self.txt, repr_b(m))
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
            log("R:%s %r", self.txt, repr_b(msg))
            return msg

    async def wr(self, buf):
        "Send buf."
        log("S:%s %r", self.txt, repr_b(buf))
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
            log("R:%s %r", self.txt, repr_b(buf[:res]))
            return res

def repr_b(b):
    if isinstance(b,bytes):
        return b
    return bytes(b)

LogBuf = LogMsg
LogBlk = LogMsg
