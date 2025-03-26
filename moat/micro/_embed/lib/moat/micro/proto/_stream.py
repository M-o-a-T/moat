from __future__ import annotations

from moat.util import NotGiven, as_proxy

from ..compat import Event, Lock, log
from .stack import BaseBuf, StackedBlk, StackedMsg

from msgpack import OutOfData

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any
    from collections.abc import Awaitable


as_proxy("_", NotGiven, replace=True)


#   @asynccontextmanager
#   def _ctx(self):
#       if self.s is None:
#           raise RuntimeError("can only be used once")
#       try:
#           yield self
#       finally:
#           s,self.s = self.s,None
#           if hasattr(s,"aclose"):
#               await s.aclose()
#           else:
#               s.close()


class _CReader:
    """
    A mix-in that processes incoming console data.
    """

    def __init__(self, cons):
        if cons is True:
            cons = 128
        self.cevt = Event()
        self.cpos = 0
        self.cbuf = bytearray(cons)
        self.cons = cons
        self.intr = 0

    async def crd(self, buf):
        """read waiting console data"""
        if not self.cons:
            raise EOFError
        if not self.cpos:
            await self.cevt.wait()
            self.cevt = Event()
        n = min(len(buf), self.cpos)
        buf[:n] = self.cbuf[:n]
        if n < self.cpos:
            self.cbuf[: self.cpos - n] = self.cbuf[n : self.cpos]
            self.cpos -= n
        else:
            self.cpos = 0
        return n

    def cput(self, b):
        """store a byte in the console buffer"""
        if self.cpos == len(self.cbuf):
            if len(self.cbuf) > 10:
                bfull = b"\n?BUF\n"
                self.cbuf[0 : len(bfull)] = bfull
                self.cpos = len(bfull)
            else:
                self.cpos = 0
        if b != 3:
            self.intr = 0
        elif self.intr > 2:
            raise KeyboardInterrupt
        else:
            self.intr += 1
        self.cbuf[self.cpos] = b
        self.cpos += 1
        self.cevt.set()


class _MsgpackMsgBuf(StackedMsg):
    """
    structured messages > MsgPack bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.

    If @console is set and a prefix is used, sends data atomically.
    Otherwise two separate write calls are used to save on message copying.

    You need to override .pack and .unpack.
    """

    cons = False

    def __init__(self, stream: BaseBuf, cfg: dict):
        #
        # console: size of console buffer, 128 if True
        # msg_prefix: int: code for start-of-packet
        #
        super().__init__(stream, cfg)
        self.w_lock = Lock()

        pref = cfg.get("msg_prefix")
        if pref is not None:
            pref = bytes((pref,))
        self.pref = pref

        cons = cfg.get("console", False)

        if cons or pref is not None:
            cfg.setdefault("unpack",{})["read_size"] = 1
        if cons:
            _CReader.__init__(self, cons)

        # we use a hacked version of msgpack with a stream-y async unpacker

    async def pack(self):
        raise NotImplementedError(self.__class__.__name__ + ".pack")

    async def unpack(self):
        raise NotImplementedError(self.__class__.__name__ + ".unpack")

    async def cwr(self, buf):
        if not self.cons:
            return
        return await self.s.wr(buf)

    def crd(self, buf) -> Awaitable:
        return _CReader.crd(self, buf)

    async def send(self, msg: Any) -> None:
        msg = self.pack(msg)
        async with self.w_lock:
            if self.pref is not None:
                if self.cons:
                    msg = self.pref + msg  # *sigh* must be atomic
                else:
                    await self.s.wr(self.pref)
            await self.s.wr(msg)

    async def recv(self) -> Any:
        if self.pref is not None:
            buf = bytearray(1)
            while True:
                if await self.s.rd(buf) != 1:
                    raise EOFError
                b = buf[0]
                if b == self.pref[0]:
                    try:
                        res = await self.unpack()
                    except OutOfData:
                        raise EOFError
                    if res is not None:
                        return res
                elif self.cons:
                    _CReader.cput(self, b)

        else:
            while True:
                try:
                    r = await self.unpack()
                except OutOfData:
                    raise EOFError
                if not isinstance(r, int):
                    return r
                elif self.cons:
                    _CReader.cput(self, r)


class _MsgpackMsgBlk(StackedMsg):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def send(self, msg):
        await self.s.snd(self.pack(msg))

    async def recv(self):
        m = await self.s.rcv()
        return self.unpacker(m)


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a MsgpackHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """

    cons = False

    def __init__(self, stream: BaseBuf, frame: dict, console: bool | int = False):
        super().__init__(None)

        from serialpacker import SerialPacker

        self.s = stream
        self.p = SerialPacker(**frame)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.w_lock = Lock()
        if console:
            _CReader.__init__(self, console)

    async def crd(self, buf):
        if not self.cons:
            raise EOFError
        return await _CReader.crd(self, buf)

    async def cwr(self, buf):
        if not self.cons:
            return
        return await super().wr(buf)

    async def recv(self):
        while True:
            while self.i < self.n:
                msg = self.p.feed(self.buf[self.i])
                self.i += 1
                if isinstance(msg, int):
                    if self.cons:
                        _CReader.cput(self, msg)
                elif msg is not None:
                    return msg

            n = await self.s.rd(self.buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n

    async def send(self, msg):
        h, msg, t = self.p.frame(msg)
        async with self.w_lock:
            if not self.cons:
                await self.s.wr(h)
                await self.s.wr(msg)
                await self.s.wr(t)
            else:
                await self.s.wr(h + msg + t)
