"""
CPython-specific stream handling.
"""
from __future__ import annotations

import sys
import anyio

from moat.util import CtxObj
from moat.micro.compat import AC_use

from ._stream import _MsgpackMsgBuf, _MsgpackMsgBlk, SerialPackerBlkBuf
from .stack import BaseBuf


class SyncStream:
    """
    Convert a MoaT stream to sync reading, via greenback.

    Use case: msgpack is not sans-IO; on CPython we don't want to
    mangle msgpack to async-ize it.
    """

    def __init__(self, stream:BaseBuf):
        self.s = stream

    def read(self, n):
        """standard sync read"""
        b = bytearray(n)
        r = greenback.await_(self.s.rd(b))
        if r < n:
            b = b[:n]
        return b

    def write(self, b):
        """standard sync write"""
        return greenback.await_(self.s.wr(b))


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


class MsgpackMsgBuf(_MsgpackMsgBuf):
    """
    structured messages > bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.
    """

    def __init__(self, stream:BaseBuf, **kw):
        #
        # console_handler: called with console bytes
        # msg_prefix: int: code for start-of-packet
        #
        super().__init__(stream, kw)
        self.kw = kw

    async def setup(self):
        await super().setup()
        self.pack = Packer(default=_encode).pack
        self._unpacker = Unpacker(SyncReadStream(stream), **self.kw)

    async def unpack(self):
        # This calls the unpacker synchronously,
        # reading from the async stream via greenback
        # because we don't want to rewrite MsgPack
        try:
            return self._unpacker.unpack()
        except OutOfData:
            raise anyio.EndOfStream

class MsgpackMsgBlk(_MsgpackMsgBlk):
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


class AnyioBuf(BaseBuf):
    """
    Adapts an anyio stream to MoaT.
    """

    async def stream() -> anyio.abc.ByteStream:
        """
        Create the stream to use.

        Use `AC_use` to arrange for closing it. This class will not do it
        for you.
        """
        raise NotImplementedError(f"Override {self.__class__.__name__}.stream")

    async def wr(self, buf) -> int:
        "basic send"
        try:
            return await self.s.send(buf) 
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise EOFError from None

    async def rd(self, buf) -> int:
        "basic receive-into"
        try:
            res = await self.s.receive(len(buf))
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise EOFError from None
        else:
            buf[: len(res)] = res
            return len(res)


class RemoteBufAnyio(anyio.abc.ByteStream):
    """
    Adapts a MoaT buf stream to a remote buffer read/write

    TODO: use remote iteration for receiving
    """
    def __init__(self, disp:SubDispatch):
        self.disp = disp

    async def receive(self, max_bytes=256):
        return await self.disp.send("rd", n=max_bytes)

    async def send(self, buf):
        await self.disp.send("wr", b=buf)

    async def aclose(self):
        pass

    async def send_eof(self):
        raise NotImplementedError("EOF")

    
class BufAnyio(CtxObj, anyio.abc.ByteStream):
    """
    Adapts a MoaT Buf stream to an anyio bytestream.
    """
    par = None

    def __init__(self, stream:BaseBuf):
        self.stream = stream

    async def __ainit__(self):
        self.par = await self.stream.__ainit__()

    async def __aexit__(self, *tb):
        return await self.stream.__aexit__(*tb)


    async def receive(self, max_bytes=256):
        b = bytearray(max_bytes)
        r = await self.par.rd(b)
        if r == max_bytes:
            return b
        elif r <= max_bytes>>2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def send(self, buf):
        await self.par.wr(buf)


class SingleAnyioBuf(AnyioBuf):
    """
    Adapts an AnyIO stream to MoaT.

    The stream is passed to the class constructor and can only be used
    once.
    """
    def __init__(self, stream):
        self._s = stream

    async def stream(self):
        return await AC_use(self, self._s)


class ProcessBuf(AnyioBuf):
    """
    A stream that connects to an external process.
    """
    def __init__(self, argv, **kw):
        super().__init__()
        self.argv = argv
        kw.setdefault("stderr", sys.stderr)
        kw.setdefault("checked", True)
        self.kw = kw

    def args(self):
        """Keyword arguments for starting the process.

        Default is whatever has been passed to the ProcessBuf constructor."""
        return self.kw

    async def stream(self):
        proc = await AC_use(self, await anyio.open_process(self.argv, **self.args()))
        s = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
        async def _close():
            with anyio.CancelScope(shield=True):
                await s.aclose()
                try:
                    with anyio.fail_after(2):
                        await proc.wait()
                except TimeoutError:
                    proc.kill()
        await AC_use(self, _close)
        return s

