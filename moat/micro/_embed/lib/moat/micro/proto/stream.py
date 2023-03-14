from ..compat import wait_for_ms, TimeoutError, Lock
from moat.util import NotGiven, NoProxyError
try:
    from moat.util import Proxy
except ImportError:
    Proxy = None

import sys
try:
    import greenback
except ImportError:
    greenback = None
from msgpack import Packer,Unpacker, OutOfData, ExtType

from .stack import _Stacked

if greenback is not None:
    class SyncReadStream:
        def __init__(self, stream):
            self.s = stream

        def read(self, n):
            return greenback.await_(self.s.recv(n))

class _Base(_Stacked):
    def __init__(self, stream):
        super().__init__(None)
        if isinstance(stream,AIOStream):
            raise RuntimeError("ugh")
        self.s = stream

    async def aclose(self):
        self.s.close()

_Proxy = {'-': NotGiven}
_RProxy = {id(NotGiven): '-'}

def drop_proxy(p):
    if not isinstance(p,str):
        p = _RProxy[id(p)]
    r = _Proxy.pop(p)
    del _RProxy[id(r)]

def ext_proxy(code, data):
    if code == 4:
        n = data.decode("utf-8")
        try:
            return _Proxy[n]
        except KeyError:
            if Proxy is None:
                raise NoProxyError(n)
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


class MsgpackStream(_Stacked):
    # structured messages > MsgPack bytestream
    #
    # Use this if your stream is reliable (TCP, USB, …)

    def __init__(self, stream, msg_prefix=None, console_handler=None, **kw):
        # 
        # console_handler: called with console bytes
        # msg_prefix: int: code for start-of-packet
        #
        super().__init__(stream)
        self.w_lock = Lock()
        kw['ext_hook'] = ext_proxy

        if console_handler is not None or msg_prefix is not None:
            kw["read_size"]=1

        if sys.implementation.name == "micropython":
            # we use a hacked version of msgpack with a stream-y async unpacker
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
        self.msg_prefix = msg_prefix
        self.console_handler = console_handler

    async def send(self, msg):
        msg = self.pack(msg)
        async with self.w_lock:
            if self.msg_prefix is not None:
                await super().send(bytes((self.msg_prefix,)))
            await super().send(msg)

    async def recv(self):
        if self.msg_prefix is not None:
            while True:
                b = (await super().recv(1))[0]
                if b == self.msg_prefix:
                    res = await self.unpack()
                    return res
                if self.console_handler is not None:
                    self.console_handler(b)

        else:
            while True:
                try:
                    r = await self.unpack()
                except OutOfData:
                    raise EOFError
                if self.console_handler is not None and isinstance(r,int) and 0 <= r < 128:
                    self.console_handler(r)
                else:
                    return r


class MsgpackHandler(_Stacked):
    # structured messages > chunked bytestrings
    # use this for one packet per message

    def __init__(self, stream, **kw):
        super().__init__(stream)
        self.unpacker = Unpacker(None, ext_hook=ext_proxy, **kw).unpackb
        self.pack = Packer(default=default_handler).packb

    async def send(self, msg):
        await super().send(self.pack(msg))

    async def recv(self):
        m = await super().recv()
        return self.unpacker(m)


class SerialPackerStream(_Base):
    # chunked bytestrings > SerialPacker messages
    #
    # Use this (and a MsgpackHandler and a Reliable) if your AIO stream
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

    async def aclose(self):
        self.s.close()

try:
    from uasyncio import core
    from uasyncio.stream import Stream
    from uasyncio import Lock
except ImportError:
    pass
else:
    def _rdq(s):  # async 
        yield core._io_queue.queue_read(s)
    def _wrq(s):  # async 
        yield core._io_queue.queue_write(s)

    class AsyncStream(_Base):
        # adapt a sync stream
        # reads a byte at a time if no any()
        # does timed-out short reads

        _buf = None

        def __init__(self, s, sw=None, force_write=False):
            super().__init__(s)

            self._any = getattr(s, "any", lambda: 1)
            self._wlock = Lock()
            self.sw = sw or s  # write stream
            self.force_write = force_write

        async def recvi(self, buf, timeout=100):
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

        async def recv(self, n=128, timeout=100):
            buf = bytearray(n)
            i = await self.recvi(buf, timeout)
            if i < n:
                return buf[0:i]
            return buf

        async def send(self, buf):
            async with self._wlock:
                m = memoryview(buf)
                i = 0
                while i < len(buf):
                    if not self.force_write:  # XXX *sigh*
                        await _wrq(self.sw)
                    n = self.sw.write(m[i:])
                    if n:
                        i += n
                self._buf = None
                return i


    class AIOStream(_Base):
        # adapts an asyncio stream to ours
        def __init__(self, stream):
            self.s = stream.s
            self.send = stream.awrite
            self.recvi = stream.readinto
            self.aclose = stream.aclose

        async def recv(self, n=128):
            s = self.s
            buf = bytearray(n)
            res = await self.recvi(buf)
            if not res:
                raise EOFError
            if res == n:
                return buf
            elif res <= n/4:
                return buf[:res]
            else:
                return memoryview(buf)[:res]

