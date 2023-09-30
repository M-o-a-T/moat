from asyncio import core
from asyncio.stream import Stream

from .stack import BaseBuf
from ._stream import _MsgpackFold, _MsgpackMsg


def _rdq(s):  # async
    yield core._io_queue.queue_read(s)

def _wrq(s):  # async
    yield core._io_queue.queue_write(s)


class FileBuf(BaseBuf):
    """
    Bytestream > sync MicroPython stream

    Reads a byte at a time if the stream doesn't have an "any()" method.

    Times out short reads if no more data arrives.
    
    @force_write must be set if the write side doesn't support polling.

    Override the `setup` async context manager to set up and tear down the
    stream.
    """

    _buf = None
    _any = lambda: 1

    def __init__(self, force_write=False, timeout=100):
        super().__init__()
        self._wlock = Lock()
        self.force_write = force_write
        self.timeout = timeout

    @asynccontextmanager
    async def _ctx(self):
        async with self.stream() as s:
            self.s = s
            self._any = getattr(s, "any", lambda: 1)
            try:
                yield self
            finally:
                if hasattr(s,"deinit"):
                    s.deinit()
                elif hasattr(s,"close"):
                    s.close()
                    self.s = None

    @asynccontextmanager
    async def stream(self):
        raise NotImplementedError

    async def rd(self, buf):
        n = 0
        m = memoryview(buf)
        while len(m):
            if n == 0 or timeout is None:
                await _rdq(self.s)
            else:
                try:
                    await wait_for_ms(timeout, _rdq, self.s)
                except TimeoutError:
                    break
            d = self.s.readinto(m[: min(self._any(), len(m))])
            if not d:
                break
            m = m[d:]
            n += d
        return n

    async def wr(self, buf):
        async with self._wlock:
            m = memoryview(buf)
            i = 0
            while i < len(buf):
                if not self.force_write:  # XXX *sigh*
                    await _wrq(self.s)
                n = self.s.write(m[i:])
                if n:
                    i += n
            self._buf = None
            return i


# msgpack encode/decode

def _decode(code, data):
    # decode an object, possibly by building a proxy.

    if code == 4:
        n = data.decode("utf-8")
        try:
            return name2obj(n)
        except KeyError:
            if Proxy is None:
                raise NoProxyError(n)
            return Proxy(n)
    elif code == 5:
        try:
            s = Unpacker(None)
            s.feed(data)

            s, *d = list(s)
            st = d[1] if len(d) > 1 else {}
            d = d[0]
            p = name2obj(s)
            try:
                o = p(*d, **st)
            except TypeError:
                o = p(*d)
                try:
                    o.__setstate__(st)
                except AttributeError:
                    try:
                        o.__dict__.update(st)
                    except AttributeError:
                        for k, v in st.items():
                            setattr(o, k, v)
            return o
        except Exception as exc:
            print("Cannot unpack", repr(data), file=sys.stderr)
            # fall thru to ExtType
    return ExtType(code, data)


def _encode(obj):
    # encode an object by building a proxy.

    if Proxy is not None and isinstance(obj, Proxy):
        return ExtType(4, obj.name.encode("utf-8"))

    try:
        k = obj2name(obj)
        return ExtType(4, k.encode("utf-8"))
    except KeyError:
        pass
    try:
        k = obj2name(type(obj))
    except KeyError:
        k = get_proxy(obj)
        return ExtType(4, k.encode("utf-8"))
    else:
        try:
            p = obj.__reduce__
        except AttributeError:
            try:
                p = obj.__dict__
            except AttributeError:
                p = {}
                for n in dir(obj):
                    if n.startswith("_"):
                        continue
                    p[n] = getattr(obj, n)
            p = ((), p)
        else:
            p = p()
            if hasattr(p[0], "__name__"):  # grah
                if p[0].__name__ == "_reconstructor":
                    p = (p[1][0], ()) + tuple(p[2:])
                elif p[0].__name__ == "__newobj__":
                    p = (p[1][0], p[1][1:]) + tuple(p[2:])

            assert p[0] is type(obj), (obj, p)
            p = p[1:]
        return ExtType(5, packb(k) + b"".join(packb(x) for x in p))

class MsgpackMsg(_MsgpackMsg):
    def __init__(self, stream, **kw):
        super().__init__(stream, kw)
        self.kw = kw

    async def setup(self, par):
        self.pack = Packer(default=_encode).packb
        self.unpack = Unpacker(stream, **self.kw).unpack


class AIOBuf(BaseBuf):
    """
    Adapts an asyncio stream to MoaT.

    Implement an async context handler @stream to set the stream up
    (and close it when done).
    """
    s = None

    def __init__(self):
        pass

    @asynccontextmanager
    async def stream(self):
        raise NotImplementedError

    @asynccontextmanager
    async def _ctx(self):
        async with self.stream() as self.s:
            try:
                yield self
            finally:
                self.s = None

    async def wr(self, buf):
        self.s.write(buf)
        await self.s.drain()

    async def rd(self, buf):
        s = self.s
        res = await self.readinto(buf)
        if not res:
            raise EOFError
        return res

class SingleAIOBuf(AIOBuf):
    """
    Adapts an asyncio stream to MoaT.

    The stream is passed to the class constructor and can only be used
    once.
    """
    def __init__(self, stream):
        self._s = stream

    @asynccontextmanager
    def stream(self):
        s, self._s = self._s, None
        try:
            yield s
        finally:
            if hasattr(s,"deinit"):
                s.deinit()
            elif hasattr(s,"close"):
                s.close()

class MsgpackFold(_MsgpackFold):
    """
    structured messages > chunked bytestrings
                
    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """
                
    def __init__(self, stream, **kw):
        super().__init__(stream)
        self.pack = Packer(default=_encode).packb
        self.unpacker = Unpacker(None, ext_hook=_decode, **kw).unpackb
        # SIGH
        #self.unpacker = partial(unpackb, ext_hook=_decode, **kw)
        #self.pack = partial(packb, default=_encode)
        

