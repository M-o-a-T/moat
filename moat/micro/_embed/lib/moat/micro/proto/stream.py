"""
Adaptor for MicroPython streams.
"""

from __future__ import annotations


from moat.util import DProxy, NoProxyError, Proxy, get_proxy, name2obj, obj2name
from moat.micro.compat import AC_use

from ._stream import _MsgpackMsgBlk, _MsgpackMsgBuf
from .stack import BaseBuf

from msgpack import ExtType, Packer, Unpacker, packb


# msgpack encode/decode


def _decode(code, data):
    # decode an object, possibly by building a proxy.

    if code == 4:
        n = str(data, "utf-8")
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
        self.pack = Packer(default=_encode).pack
        self.unpack = Unpacker(self.s, ext_hook=_decode, **self.cfg.get("unpack", {})).unpack


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
        return len(buf)

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
