"""
CPython-specific stream handling.
"""

from __future__ import annotations

import anyio
import fcntl
import os
import sys
import termios
from contextlib import asynccontextmanager

from moat.util import CtxObj
from moat.lib.codec import get_codec
from moat.util.compat import AC_use

from ._stream import _CBORMsgBlk, _CBORMsgBuf
from .stack import BaseBuf

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.cmd.tree.dir import SubDispatch


class ProcessDeadError(RuntimeError):
    """Process has died"""


class CBORMsgBuf(_CBORMsgBuf):
    """
    structured messages > bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec("std-cbor")


class CBORMsgBlk(_CBORMsgBlk):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec("std-cbor")


class AnyioBuf(BaseBuf):
    """
    Adapts an anyio stream to MoaT.
    """

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


class FilenoBuf(BaseBuf):
    """
    Adapts a Unix file descriptor to MoaT.

    """

    rfd: int
    wfd: int
    rfl: int
    wfl: int
    term: bytes

    def __init__(self, cfg, fd: int, wfd: int | None = None):
        super().__init__(cfg)
        self.rfd = fd
        self.wfd = fd if wfd is None else wfd
        self.term = None

    async def stream(self) -> anyio.abc.ByteStream:
        "Dummy here"
        pass

    async def setup(self):
        "Change to nonblocking and raw"
        self.rfl = fcntl.fcntl(self.rfd, fcntl.F_SETFL, 0)
        if self.rfd != self.wfd:
            self.wfl = fcntl.fcntl(self.wfd, fcntl.F_SETFL, 0)

        fcntl.fcntl(self.rfd, fcntl.F_SETFL, self.rfl | os.O_NDELAY)
        if self.rfd != self.wfd:
            fcntl.fcntl(self.wfd, fcntl.F_SETFL, self.wfl | os.O_NDELAY)

        try:
            self.term = termios.tcgetattr(self.rfd)
        except OSError:
            pass
        else:
            new = self.term[:]
            new[3] = new[3] & ~termios.ICANON & ~termios.ECHO & ~termios.ISIG
            new[6][termios.VMIN] = 1
            new[6][termios.VTIME] = 0
            termios.tcsetattr(self.rfd, termios.TCSANOW, new)

    async def teardown(self):
        "Return to blocking and cooked"
        fcntl.fcntl(self.rfd, fcntl.F_SETFL, self.rfl)
        if self.rfd != self.wfd:
            fcntl.fcntl(self.wfd, fcntl.F_SETFL, self.wfl)
        if self.term is not None:
            termios.tcsetattr(self.rfd, termios.TCSANOW, self.term)

    async def wr(self, buf) -> int:
        "basic send"
        on = len(buf)
        while True:
            n = len(buf)
            await anyio.wait_writable(self.wfd)
            nn = os.write(self.wfd, buf)
            if nn <= 0:
                raise OSError
            if nn == n:
                return on
            buf = memoryview(buf)[nn:]

    async def rd(self, buf) -> int:
        "basic receive-into"
        await anyio.wait_readable(self.rfd)
        bf = os.read(self.rfd, len(buf))
        buf[: len(bf)] = bf
        return len(bf)


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
                    try:
                        proc.kill()
                        with anyio.CancelScope(shield=True):
                            await proc.wait()
                        raise
                    finally:
                        proc = None  # noqa:PLW2901
        finally:
            if proc is not None and proc.returncode != 0 and proc.returncode != -9:
                raise ProcessDeadError(f"{self} died with {proc.returncode}")

    async def setup(self):  # noqa:D102
        pass

    async def stream(self):  # noqa:D102
        raise RuntimeError("should not be called")
