from __future__ import annotations

from moat.util import NotGiven
from moat.lib.codec.proxy import as_proxy
from moat.util.compat import Event, Lock, log

from .stack import BaseBuf, StackedBlk, StackedMsg

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.codec import Codec

    from collections.abc import Awaitable
    from typing import Any


as_proxy("_", NotGiven)


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

    def __init__(self, cons: bool | int):
        if cons is True:
            try:
                import machine  # noqa: PLC0415,F401
            except ImportError:
                cons = 32768
            else:
                cons = 240
        self.cevt = Event()
        self.cpos = 0
        self.cbuf = bytearray(cons)
        self.cons = cons
        self.intr = 0

    async def crd(self, buf: bytearray):
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

    def cput(self, b: int):
        """store a byte in the console buffer"""
        if self.cpos == len(self.cbuf):
            if len(self.cbuf) > 100:
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


class _CBORMsgBuf(StackedMsg):
    """
    structured messages > CBOR bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.

    If @console is set and a prefix is used, sends data atomically.
    Otherwise two separate write calls are used to save on message copying.
    """

    cons = False
    codec: Codec = None

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
        if cons:
            _CReader.__init__(self, cons)

    async def cwr(self, buf):
        if not self.cons:
            return
        return await self.s.wr(buf)

    def crd(self, buf) -> Awaitable:
        return _CReader.crd(self, buf)

    async def send(self, msg: Any) -> None:
        try:
            msg = self.codec.encode(msg)
        except Exception:
            log("MSG:\n%r", msg)
            raise
        async with self.w_lock:
            if self.pref is not None:
                if self.cons:
                    msg = self.pref + msg  # must be atomic
                else:
                    await self.s.wr(self.pref)
            await self.s.wr(msg)

    async def recv(self) -> Any:
        """
        Receive the next object.
        """
        # Pre+postcondition: the codec does not have an object in progress.

        buf = bytearray(64)
        if self.pref is None:
            # easy case
            while True:
                try:
                    r = next(self.codec)
                except StopIteration:
                    n = await self.s.rd(buf)
                    self.codec.feed(memoryview(buf)[:n])
                else:
                    if self.cons and isinstance(r, int) and r >= 0:
                        _CReader.cput(self, r)
                    else:
                        return r

        while True:
            b = bytearray(1)
            while True:
                # read until we get a prefix byte
                if self.codec.unfeed(b) == 0:
                    n = await self.s.rd(buf)
                    self.codec.feed(memoryview(buf)[:n])
                elif b == self.pref:
                    break
                elif self.cons:
                    _CReader.cput(self, b[0])

            while True:
                # read until we get an object
                try:
                    return next(self.codec)
                except StopIteration:
                    pass

                n = await self.s.rd(buf)
                self.codec.feed(memoryview(buf)[:n])


class _CBORMsgBlk(StackedMsg):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def send(self, msg):
        await self.s.snd(self.codec.encode(msg))

    async def recv(self):
        m = await self.s.rcv()
        return self.codec.decode(m)


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a CBORHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """

    cons = False

    def __init__(self, stream: BaseBuf, frame: dict, console: bool | int = False):
        super().__init__(None)

        from serialpacker import SerialPacker  # noqa: PLC0415

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
