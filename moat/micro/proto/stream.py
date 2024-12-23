"""
CPython-specific stream handling.
"""

from __future__ import annotations

import anyio
import sys
from contextlib import asynccontextmanager
from functools import partial

from moat.util import CtxObj, DProxy, Proxy, get_proxy, name2obj, obj2name
from moat.micro.compat import AC_use, log

from ._stream import _MsgpackMsgBlk, _MsgpackMsgBuf
from .stack import BaseBuf

import greenback
from msgpack import ExtType, OutOfData, Packer, Unpacker, packb, unpackb

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.cmd.tree.dir import SubDispatch

# ruff:noqa:B904


class ProcessDeadError(RuntimeError):
    """Process has died"""


class SyncStream:
    """
    Convert a MoaT BaseBuf to sync reading, via greenback.

    Use case: msgpack is not sans-IO; on CPython we don't want to
    mangle msgpack to async-ize it.
    """

    def __init__(self, stream: BaseBuf, max_n=10240):
        self.s = stream
        self.max_n = max_n

    def read(self, n):
        """standard sync read"""
        n = min(n, self.max_n)
        b = bytearray(n)
        r = greenback.await_(self.s.rd(b))
        if r < n:
            b = b[:r]
        return bytes(b)  # stupid msgpack decoder is stupid

    def write(self, b):
        """standard sync write"""
        return greenback.await_(self.s.wr(b))


# msgpack encode/decode


def _decode(code, data):
    # decode an object, possibly by building a proxy.

    if code == 4:
        n = str(data, "utf-8")
        try:
            return name2obj(n)
        except KeyError:
            return Proxy(n)
    elif code == 5:
        try:
            s = Unpacker(None, strict_map_key=False)
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
            log("Cannot unpack %r", data, err=exc)
            # fall thru to ExtType
    return ExtType(code, data)


def _encode(obj):
    # encode an object by building a proxy.

    if isinstance(obj, Proxy):
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
    structured messages > bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pack = Packer(default=_encode).pack
        self._unpacker = Unpacker(
            SyncStream(self.s),
            strict_map_key=False,
            ext_hook=_decode,
            **self.cfg.get("pack", {}),
        )

    async def unpack(self):
        """
        This calls the unpacker synchronously,
        reading from the async stream via greenback
        because we don't want to rewrite MsgPack
        """
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

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pack = Packer(default=_encode).pack
        self.unpacker = partial(
            unpackb,
            strict_map_key=False,
            ext_hook=_decode,
            **self.cfg.get("pack", {}),
        )


class AnyioBuf(BaseBuf):
    """
    Adapts an anyio stream to MoaT.
    """

    async def setup(self):
        """
        The default simply opens the stream and assigns it to ``s``.
        """
        self.s = await self.stream()

    async def stream(self) -> anyio.abc.ByteStream:
        """
        Create the stream to use.

        Use `AC_use` to arrange for closing it. This class will not do it
        for you.
        """
        raise NotImplementedError(f"Override {self.__class__.__name__}.stream")

    async def wr(self, buf) -> int:
        "basic send"
        try:
            await self.s.send(buf)
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            raise EOFError from None
        else:
            return len(buf)

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

    def __init__(self, disp: SubDispatch):
        self.disp = disp

    async def receive(self, max_bytes=256):
        "forward to ``.rd``"
        return await self.disp.rd(n=max_bytes)

    async def send(self, buf):
        "forward to ``.wr``"
        await self.disp.wr(b=buf)

    async def aclose(self):
        "no-op"

    async def send_eof(self):
        "not implemented"
        raise NotImplementedError("EOF")


class BufAnyio(anyio.abc.ByteStream):
    """
    Adapts a MoaT Buf stream to an anyio bytestream.
    """

    par = None

    def __init__(self, stream: BaseBuf):
        self.stream = stream

    async def __aenter__(self):
        self.s = await self.stream.__aenter__()

    async def __aexit__(self, *tb):
        return await self.stream.__aexit__(*tb)

    async def receive(self, max_bytes=256):
        "forward to ``.rd``"
        b = bytearray(max_bytes)
        r = await self.s.rd(b)
        if r == max_bytes:
            return b
        elif r <= max_bytes >> 2:
            return bytes(b[:r])
        else:
            b = memoryview(b)
            return b[:r]

    async def send(self, buf):
        "forward to ``.wr``"
        await self.s.wr(buf)


class SingleAnyioBuf(AnyioBuf):
    """
    Adapts an AnyIO stream to MoaT.

    The stream is passed to the class constructor and can only be used
    once.
    """

    def __init__(self, stream):
        self._s = stream

    async def stream(self):  # noqa:D102
        return await AC_use(self, self._s)


class ProcessBuf(CtxObj, AnyioBuf):
    """
    A stream that connects to an external process.

    Config:
    - exec: path to the executable
    - argv: Arguments
    - env: environment vars

    You can set these as attributes on the object, statically or in your
    subclass's `setup` method. Configuration can then override them.
    """

    proc: anyio.Process = None
    exec: str | None = None
    cwd: str | None = None
    argv: list[str] | None = None
    env: dict[str, str] | None = None

    def __init__(self, cfg, executable: str | None = None, **kw):
        super().__init__(cfg)
        kw.setdefault("stderr", sys.stderr)
        self.kw = kw
        self.exec = executable

    def open_args(self):
        """Return keyword arguments for `anyio.open_process`.

        Default is whatever has been passed to the ProcessBuf constructor.
        """
        # Ugh, anyio doesn't accept 'executable'
        if self.exec is not None:
            # self.kw["executable"] = self.exec
            self.argv[0] = self.exec
        elif "/" in (a0 := str(self.argv[0])):  # noqa:F841 # a0 unused
            # self.kw["executable"] = a0
            # self.argv[0] = a0.rsplit("/",1)[1]
            pass
        for k in ("cwd", "env"):
            if (v := getattr(self, k)) is not None:
                self.kw[k] = v

        return self.kw

    @asynccontextmanager
    async def _ctx(self):
        await self.setup()
        proc = None
        for k in ("exec", "argv", "env", "cwd"):
            if (v := self.cfg.get(k, None)) is not None:
                setattr(self, k, v)
        if self.argv is None:
            raise ValueError("Don't know what")

        try:
            async with await anyio.open_process(self.argv, **self.open_args()) as proc:
                try:
                    async with SingleAnyioBuf(
                        anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout),
                    ) as s:
                        yield s
                    await proc.wait()
                except BaseException:
                    proc.kill()
                    with anyio.CancelScope(shield=True):
                        await proc.wait()
                    raise
        finally:
            if proc is not None and proc.returncode != 0 and proc.returncode != -9:
                raise ProcessDeadError(f"{self} died with {proc.returncode}")

    async def setup(self):  # noqa:D102
        pass

    async def stream(self):  # noqa:D102
        raise RuntimeError("should not be called")
