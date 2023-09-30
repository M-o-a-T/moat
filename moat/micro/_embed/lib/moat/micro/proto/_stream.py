from __future__ import annotations

import sys
from functools import partial

from moat.util import NoProxyError, NotGiven, as_proxy, name2obj, obj2name

from ..compat import Lock, TimeoutError, wait_for_ms, const, Event
from .stack import StackedBuf, BaseBuf, StackedMsg, StackedBlk


try:
    from moat.util import Proxy, get_proxy
except ImportError:
    Proxy = None

    def get_proxy(x):
        raise NotImplementedError(f"get_proxy({repr(x)})")

MPy = const(sys.implementation.name == "micropython")

from msgpack import ExtType, OutOfData, Packer, Unpacker, packb, unpackb
from serialpacker import FRAME_START, SerialPacker

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
        self.cwait = Event()
        self.cpos = 0
        self.cbuf = bytearray(cons)
        self.cons = cons

    async def crd(self, buf):
        """read waiting console data"""
        if not self.cons:
            raise EOFError
        if not self.cpos:
            await cevt.wait()
            cevt = Event()
        n = min(len(buf),cpos)
        buf[:n] = self.cbuf[:n]
        if n < self.cpos:
            self.cbuf[:self.cpos-n] = self.cbuf[n:self.cpos]
            self.cpos -= n
        else:
            self.cpos = 0
        return n

    def cput(self, b):
        """store a byte in the console buffer"""
        if self.cpos == len(self.cbuf):
            if len(self.cbuf) > 10:
                bfull = b"\n?BUF\n"
                self.cpos[0:self.cpos] = bfull
                self.cpos = len(bfull)
            else:
                self.cpos = 0
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

    You need to override .pack and .unpack
    """
    cons = False

    def __init__(self, stream:BaseBuf, kw:dict):
        #
        # console: size of console buffer, 128 if True
        # msg_prefix: int: code for start-of-packet
        #
        super().__init__(stream)
        self.w_lock = Lock()
        kw['ext_hook'] = _decode

        pref = kw.pop("msg_prefix", None)
        if pref is not None:
            pref = bytes((pref,))
        self.pref = pref

        cons = kw.pop["console"]

        if cons or msg_prefix is not None:
            kw["read_size"] = 1
        if cons:
            _CReader.__init__(self, cons)

        # we use a hacked version of msgpack with a stream-y async unpacker

    async def unpack(self):
        raise NotImplementedError(self.__class__.__name__ + ".unpack")

    async def cwr(self, buf):
        if not self.cons:
            return
        return await super().wr(buf)

    async def crd(self, buf):
        return _CReader.crd(self, buf)

    async def send(self, msg:Any) -> None:
        msg = self.pack(msg)
        async with self.w_lock:
            if self.pref is not None:
                if self.cons:
                    msg = self.pref+msg  # *sigh* must be atomic
                else:
                    await super().wr(self.pref)
            await super().wr(msg)

    async def recv(self) -> Any:
        if self.pref is not None:
            buf = bytearray(1)
            while True:
                if await self.par.rd(buf) != 1:
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

    def __init__(self, stream:BaseBlk, **kw):
        super().__init__(stream)
        self.pack = Packer(default=_encode).packb
        self.unpacker = Unpacker(None, ext_hook=_decode, **kw).unpackb
        # SIGH
        #self.unpacker = partial(unpackb, ext_hook=_decode, **kw)
        #self.pack = partial(packb, default=_encode)

    async def send(self, msg):
        await super().snd(self.pack(msg))

    async def recv(self):
        m = await super().rcv()
        return self.unpacker(m)


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a MsgpackHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """
    cons = False

    def __init__(self, stream:BaseBuf, frame:dict, cons:bool|int = False):
        super().__init__(None)

        self.s = stream
        self.p = SerialPacker(**frame)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.w_lock = Lock()
        if cons:
            _CReader.__init__(self, cons)

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
                await self.s.wr(h+msg+t)

