from ..compat import wait_for_ms, TimeoutError, Lock
from ..util import NotGiven
try:
    from ..util import Proxy
except ImportError:
    Proxy = None

import sys
try:
    import greenback
except ImportError:
    greenback = None
from msgpack import Packer,Unpacker, OutOfData, ExtType

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

_Proxy = {'-': NotGiven}
_RProxy = {id(NotGiven): '-'}

def drop_proxy(p):
    r = _Proxy.pop(p)
    del _RProxy[id(r)]

def ext_proxy(code, data):
    if code == 4:
        n = data.decode("utf-8")
        try:
            return _Proxy[n]
        except KeyError:
            if Proxy is None:
                raise
            return Proxy(n)
    return ExtType(code, data)

_pkey = 1
def default_handler(obj):
    if Proxy is not None and isinstance(obj,Proxy):
        return ExtType(4, obj.name.encode("utf-8"))

    try:
        k = _RProxy[id(obj)]
    except KeyError:
        global _pkey
        k = "p_"+str(_pkey)
        _pkey += 1
        _Proxy[k] = obj
        _RProxy[id(obj)] = k
    return ExtType(4, k.encode("utf-8"))


class MsgpackStream(_Base):
    # structured messages > MsgPack bytestream
    #
    # Use this if your stream is reliable (TCP, USB, …)

    def __init__(self, stream, console=None, console_handler=None, **kw):
        super().__init__(stream)
        self.w_lock = Lock()
        kw['ext_hook'] = ext_proxy

        if isinstance(console,int) and not isinstance(console,bool):
            kw["read_size"]=1

        if sys.implementation.name == "micropython":
            # we use a hacked version of msgpack that does async reading
            self.pack = Packer(default=default_handler).packb
            self.unpack = Unpacker(stream, **kw).unpack
        else:
            # regular Python: msgpack uses a sync read call, so use greenback to async-ize it
            self.pack = Packer(default=default_handler).pack
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
        async with self.w_lock:
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
        self.unpacker = Unpacker(stream, ext_hook=ext_proxy, **kw).unpackb
        self.pack = Packer(default=default_handler).packb

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
        self.w_lock = Lock()

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
        h,msg,t = self.p.frame(msg)
        async with self.w_lock:
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

