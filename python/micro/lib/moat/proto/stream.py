from ..compat import wait_for_ms, TimeoutError

import sys
try:
    import greenback
except ImportError:
    greenback = None
from msgpack import Packer,Unpacker, OutOfData

import logging
logger = logging.getLogger(__name__)

from . import _Stacked

if greenback is not None:
    class SyncReadStream:
        def __init__(self, stream):
            self.s = stream

        def read(self, n):
            return greenback.await_(self.s.read(n))

class _Base(_Stacked):
    def __init__(self, stream):
        super().__init__(None)
        self.s = stream

class MsgpackStream(_Base):
    # structured messages > MsgPack bytestream
    #
    # Use this if your stream is reliable (TCP, USB, …)

    def __init__(self, stream, console=None, console_handler=None, **kw):
        super().__init__(stream)
        if isinstance(console,int) and not isinstance(console,bool):
            kw["read_size"]=1

        if sys.implementation.name == "micropython":
            # we use a hacked version of msgpack that does async reading
            self.pack = Packer().packb
            self.unpack = Unpacker(stream, **kw).unpack
        else:
            # regular Python: msgpack uses a sync read call, so use greenback to async-ize it
            self.pack = Packer().pack
            self.unpacker = Unpacker(SyncReadStream(stream), **kw)
            async def unpack():
                import anyio
                try:
                    return self.unpacker.unpack()
                except OutOfData:
                    raise anyio.EndOfStream
            self.unpack = unpack
        self.console = console
        self.console_handler = console_handler

    async def init(self):
        if greenback is not None:
            await greenback.ensure_portal()

    async def send(self, msg):
        msg = self.pack(msg)
        if isinstance(self.console,int) and not isinstance(self.console, bool):
            msg = bytes((self.console,)) + msg
        await self.s.write(msg)

    async def recv(self):
        if isinstance(self.console, int) and not isinstance(self.console, bool):
            while True:
                b = (await self.s.read(1))[0]
                if b == self.console:
                    res = await self.unpack()
                    return res
                self.console_handler(b)

        else:
            while True:
                r = await self.unpack()
                if self.console is not None and isinstance(r,int):
                    self.console_handler(r)
                else:
                    return r


class MsgpackHandler(_Stacked):
    # structured messages > chunked bytestrings

    def __init__(self, stream, **kw):
        super().__init__(stream)
        self.unpacker = Unpacker(stream, **kw).unpackb
        self.pack = Packer().packb

    async def send(self, msg):
        await super().send(self.pack(msg))

    async def recv(self):
        m = await self.parent.recv()
        return self.unpacker(m)


class SerialPackerStream(_Base):
    # chunked bytestrings > SerialPacker messages
    #
    # Use this (and a MsgpackHandler and a Reliable) if your stream
    # is unreliable (TTL serial).

    def __init__(self, stream, console=None, console_handler=None, **kw):
        super().__init__(None)

        from serialpacker import SerialPacker

        self.s = stream
        self.p = SerialPacker(**kw)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.console = console
        self.console_handler = console_handler

    async def recv(self):
        while True:
            while self.i < self.n:
                msg = self.p.feed(c[self.i])
                self.i += 1
                if isinstance(msg,int):
                    if self.console is not None:
                        self.console_handler(msg)
                elif msg is not None:
                    return msg

            n = await self.s.readinto(buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n


    async def send(self, msg):
        h,t = self.p.frame(msg)
        await self.s.write(h+msg+t)


try:
    from uasyncio import core
    from uasyncio.stream import Stream
    from uasyncio import Lock
except ImportError:
    pass
else:
    async def _rdq(s):
        yield core._io_queue.queue_read(s)
    async def _wrq(s):
        yield core._io_queue.queue_write(s)


    class AsyncStream(Stream):
        # convert a sync stream to an async one
        # reads a byte at a time if no any()
        # does timed-out short reads

        def __init__(self, s, sw=None, force_write=False, **kw):
            super().__init__(s, **kw)

            def one():
                return 1
            self._any = getattr(s, "any", one)
            self._wlock = Lock()
            self.sw = sw or s
            self.force_write = force_write

        async def readinto(self, buf, timeout=100):
            i = 0
            m = memoryview(buf)
            while i < len(buf):
                if i==0 or timeout<0:
                    await _rdq(self.s)
                else:
                    try:
                        await wait_for_ms(timeout, _rdq, self.s)
                    except TimeoutError:
                        break
                d = self.s.readinto(m[i:i+min(self._any(), len(buf)-i)])
                i += d
            return i

        async def read(self, n, timeout=100):
            buf = bytearray(n)
            i = await self.readinto(buf, timeout)
            if i < n:
                return buf[0:i]
            return buf

        async def readexactly(self, n):
            buf = bytearray(n)
            return await self.readinto(buf,timeout=-1)

        async def write(self, buf):
            # no we do not use a sync "write" plus an async "drain".
            async with self._wlock:
                m = memoryview(buf)
                i = 0
                while i < len(buf):
                    if not self.force_write:  # XXX *sigh*
                        await _wrq(self.sw)
                    n = self.sw.write(m[i:])
                    if n:
                        i += n
                return i

