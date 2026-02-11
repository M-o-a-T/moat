"""
This module contains msgpack-based helper functions and classes.

TODO add CBOR.
"""

from __future__ import annotations

import anyio

from moat.lib.codec import Codec

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import AsyncResource
    from pathlib import Path as FSPath
    from types import TracebackType

    from typing import Self

__all__ = ["MsgReader", "MsgWriter"]


class _MsgRW:
    """
    Common base class for :class:`MsgReader` and :class:`MsgWriter`.
    """

    _mode: str

    def __init__(
        self,
        path: anyio.Path | FSPath | str | None = None,
        stream: AsyncResource | None = None,
        codec: Codec | str | None = None,
    ) -> None:
        if (path is None) == (stream is None):
            raise RuntimeError("You need to specify either path or stream")

        if codec is None:
            raise ValueError("No default codec")
        if not isinstance(codec, Codec):
            from moat.lib.codec import get_codec  # noqa: PLC0415

            codec = get_codec(codec)

        path_obj: anyio.Path | None
        if isinstance(path, anyio.Path):
            path_obj = path
        elif path is not None:
            path_obj = anyio.Path(path)
        else:
            path_obj = None
        self.path: anyio.Path | None = path_obj

        self.stream: AsyncResource | None = stream
        self.codec: Codec = codec

    async def __aenter__(self) -> Self:
        if self.path is not None:
            p: anyio.Path | str = self.path
            if p == "-":
                if self._mode[0] == "r":
                    p = "/dev/stdin"
                else:
                    p = "/dev/stdout"
            self.stream = await anyio.open_file(p, self._mode)  # type: ignore[arg-type]  # _mode is str literal in subclasses
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.path is not None:
            assert self.stream is not None  # stream is set in __aenter__
            with anyio.CancelScope(shield=True):
                await self.stream.aclose()


class MsgReader(_MsgRW):
    """Read a stream of messages (encoded with some codec) from a file.

    Usage::

        async with MsgReader(path="/tmp/msgs.pack") as f:
            async for msg in f:
                process(msg)

    Arguments:
      buflen (int): The read buffer size. Defaults to 4k.
      path (str): the file to write to.
      stream: the stream to write to.

    Exactly one of ``path`` and ``stream`` must be used.
    """

    _mode: str = "rb"

    def __init__(self, *a: Any, buflen: int = 4096, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.buflen: int = buflen

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Any:
        while True:
            try:
                return next(self.codec)
            except StopIteration:
                pass

            assert self.stream is not None  # stream is set in __aenter__
            d = await self.stream.read(self.buflen)  # type: ignore[attr-defined]  # AsyncFile has read
            if d == b"":
                raise StopAsyncIteration
            self.codec.feed(d)


class MsgWriter(_MsgRW):
    """Write a stream of messages to a file (encoded with some codec).

    Usage::

        async with MsgWriter("/tmp/msgs.pack", codec="std-cbor") as f:
            for msg in some_source_of_messages():  # or "async for"
                await f(msg)

    Arguments:
      buflen (int): The buffer size. Defaults to 64k.
      path (str): the file to write to.
      stream: the stream to write to.

    Exactly one of ``path`` and ``stream`` must be used.

    The stream is buffered. Call :meth:`flush` to flush the buffer.
    """

    _mode: str = "wb"

    def __init__(self, *a: Any, buflen: int = 65536, **kw: Any) -> None:
        super().__init__(*a, **kw)

        self.buf: list[bytes] = []
        self.buflen: int = buflen
        self.curlen: int = 0
        self.excess: int = 0

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.stream is not None  # stream is set in __aenter__
        with anyio.fail_after(2, shield=True):
            if self.buf:
                await self.stream.write(b"".join(self.buf))  # type: ignore[attr-defined]  # AsyncFile has write
            await super().__aexit__(exc_type, exc_val, exc_tb)

    async def __call__(self, msg: Any) -> None:
        """Write a message (bytes) to the buffer.

        Flushing writes a multiple of ``buflen`` bytes."""
        assert self.stream is not None  # stream is set in __aenter__
        msg_bytes = self.codec.encode(msg)
        if not isinstance(msg_bytes, bytes):
            msg_bytes = bytes(msg_bytes)
        self.buf.append(msg_bytes)
        self.curlen += len(msg_bytes)
        if self.curlen + self.excess >= self.buflen:
            buf = b"".join(self.buf)
            pos = self.buflen * ((self.curlen + self.excess) // self.buflen) - self.excess
            assert pos > 0
            wb, buf = buf[:pos], buf[pos:]
            self.curlen = len(buf)
            self.buf = [buf]
            self.excess = 0
            await self.stream.write(wb)  # type: ignore[attr-defined]  # AsyncFile has write

    async def flush(self, force: bool = True) -> None:
        """Flush the buffer.

        @force: do write partial data.
        """
        assert self.stream is not None  # stream is set in __aenter__
        if self.buf:
            buf = b"".join(self.buf)
            self.buf = []
            self.excess = (self.excess + len(buf)) % self.buflen
            await self.stream.write(buf)  # type: ignore[attr-defined]  # AsyncFile has write
            if force:
                await self.stream.flush()  # type: ignore[attr-defined]  # AsyncFile has flush
