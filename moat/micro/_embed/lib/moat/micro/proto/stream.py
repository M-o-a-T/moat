"""
Adaptor for MicroPython streams.
"""
from __future__ import annotations

from asyncio import core

from moat.util import DProxy, NoProxyError, Proxy, get_proxy, name2obj, obj2name
from moat.micro.compat import AC_use, Lock, TimeoutError, wait_for_ms

from ._stream import _MsgpackMsgBlk, _MsgpackMsgBuf
from .stack import BaseBuf

from msgpack import ExtType, Packer, Unpacker, packb


def _rdq(s):  # async
    yield core._io_queue.queue_read(s)  # noqa:SLF001


def _wrq(s):  # async
    yield core._io_queue.queue_write(s)  # noqa:SLF001


class FileBuf(BaseBuf):
    """
    Bytestream > sync MicroPython stream

    Reads a byte at a time if the stream doesn't have an "any()" method.

    Times out short reads if no more data arrives.

    @force_write must be set if the write side doesn't support polling.

    Override the `setup` async context manager to set up and tear down the
    stream. It must yield either a single file or a stdin/stdout tuple.
    """

    _buf = None
    _any = lambda: 1  # noqa:E731

    def __init__(self, force_write=False, timeout=100):
        super().__init__({})
        self._wlock = Lock()
        self.force_write = force_write
        self.timeout = timeout

    async def setup(self):  # noqa:D102
        s = await self.stream()
        if isinstance(s, tuple):
            self.rs, self.ws = s
        else:
            self.rs = self.ws = s
        self._any = getattr(self.rs, "any", lambda: 1)

    async def stream(self):  # noqa:D102
        raise NotImplementedError

    async def rd(self, buf):
        "forwards to ``.read(into)``"
        n = 0
        m = memoryview(buf)
        while len(m):
            if n == 0 or self.timeout is None:
                await _rdq(self.rs)
            else:
                try:
                    await wait_for_ms(self.timeout, _rdq, self.rs)
                except TimeoutError:
                    break
            d = self.rs.readinto(m[: min(self._any(), len(m))])
            if not d:
                break
            m = m[d:]
            n += d
        return n

    async def wr(self, buf):
        "forwards to ``.write``"
        async with self._wlock:
            m = memoryview(buf)
            i = 0
            while i < len(buf):
                if not self.force_write:  # XXX *sigh*
                    await _wrq(self.ws)
                n = self.ws.write(m[i:])
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
                raise NoProxyError(n) from None
            return Proxy(n)
    elif code == 5:
        s = Unpacker(None)
        s.feed(data)

        s, *d = list(s)
        st = d[1] if len(d) > 1 else {}
        d = d[0]
        try:
            p = name2obj(s)
            o = p(*d, **st)
        except KeyError:
            o = DProxy(s, *d, **st)
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
    return ExtType(code, data)


def _encode(obj):
    # encode an object by building a proxy.

    if type(obj) is Proxy:
        return ExtType(4, obj.name.encode("utf-8"))
    if type(obj) is DProxy:
        return ExtType(
            5,
            packb(obj.name) + packb(obj.a, default=_encode) + packb(obj.k, default=_encode),
        )

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
        return ExtType(5, packb(k) + b"".join(packb(x, default=_encode) for x in p))


class MsgpackMsgBuf(_MsgpackMsgBuf):
    """
    structured messages > stream of bytes

    Use this if the layer below does not support/require byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pack = Packer(default=_encode).packb
        self.unpack = Unpacker(self.s, ext_hook=_decode, **self.cfg.get("pack", {})).unpack


class MsgpackMsgBlk(_MsgpackMsgBlk):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pack = Packer(default=_encode).packb
        self.unpack = Unpacker(self.s, ext_hook=_decode, **self.cfg.get("pack", {})).unpack


class AIOBuf(BaseBuf):
    """
    Adapts an asyncio stream to MoaT.

    Implement an async context handler @stream to set the stream up
    (and close it when done).
    """

    s = None

    def __init__(self):
        pass

    async def stream(self):  # noqa:D102
        raise NotImplementedError

    async def wr(self, buf):
        "translates to ``.write`` + ``.drain``"
        self.s.write(buf)
        await self.s.drain()

    async def rd(self, buf):
        "translates to ``.readinto``"
        s = self.s
        res = await s.readinto(buf)
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

    async def stream(self):  # noqa:D102
        if self._s is None:
            raise RuntimeError("used twice")
        s, self._s = self._s, None
        await AC_use(self, self._destr)
        return s

    def _destr(self):
        if hasattr(self.s, "deinit"):
            self.s.deinit()
        elif hasattr(self.s, "close"):
            self.s.close()
