"""
This module contains msgpack-based helper functions and classes.

TODO add CBOR.
"""

from __future__ import annotations

import anyio

from moat.lib.codec import Codec
from pathlib import Path as FSPath

__all__ = ["MsgReader", "MsgWriter"]


class _MsgRW:
    """
    Common base class for :class:`MsgReader` and :class:`MsgWriter`.
    """

    _mode: str = None

    def __init__(self, path:anyio.Path|FSPath|str|None=None, stream=None, codec:Codec|str=None):
        if (path is None) == (stream is None):
            raise RuntimeError("You need to specify either path or stream")

        if codec is None:
            raise ValueError("No default codec")
        if not isinstance(codec, Codec):
            from moat.util import get_codec
            codec = get_codec(codec)

        if isinstance(path,anyio.Path):
            pass
        elif path is not None:
            path = anyio.Path(path)
        self.path = path

        self.stream = stream
        self.codec = codec

    async def __aenter__(self):
        if self.path is not None:
            p = self.path
            if p == "-":
                if self._mode[0] == "r":  # pylint: disable=unsubscriptable-object
                    p = "/dev/stdin"
                else:
                    p = "/dev/stdout"
            self.stream = await anyio.open_file(p, self._mode)
        return self

    async def __aexit__(self, *tb):
        if self.path is not None:
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

    _mode = "rb"

    def __init__(self, *a, buflen=4096, **kw):
        super().__init__(*a, **kw)
        self.buflen = buflen

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            try:
                return next(self.codec)
            except StopIteration:
                pass

            d = await self.stream.read(self.buflen)
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

    _mode = "wb"

    def __init__(self, *a, buflen=65536, **kw):
        super().__init__(*a, **kw)

        self.buf = []
        self.buflen = buflen
        self.curlen = 0
        self.excess = 0

    async def __aexit__(self, *tb):
        with anyio.fail_after(2, shield=True):
            if self.buf:
                await self.stream.write(b"".join(self.buf))
            await super().__aexit__(*tb)

    async def __call__(self, msg):
        """Write a message (bytes) to the buffer.

        Flushing writes a multiple of ``buflen`` bytes."""
        msg = self.codec.encode(msg)
        self.buf.append(msg)
        self.curlen += len(msg)
        if self.curlen + self.excess >= self.buflen:
            buf = b"".join(self.buf)
            pos = self.buflen * ((self.curlen + self.excess) // self.buflen) - self.excess
            assert pos > 0
            wb, buf = buf[:pos], buf[pos:]
            self.curlen = len(buf)
            self.buf = [buf]
            self.excess = 0
            await self.stream.write(wb)

    async def flush(self, force=True):
        """Flush the buffer.

        @force: do write partial data.
        """
        if self.buf:
            buf = b"".join(self.buf)
            self.buf = []
            self.excess = (self.excess + len(buf)) % self.buflen
            await self.stream.write(buf)
            if force:
                await self.stream.flush()
