"""
SerialPacker protocol support for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import Lock
from moat.lib.stream import BaseBuf, StackedBlk
from moat.lib.stream.base import build_stack

from ._console import _CReader

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.stream.base import Buffer, MutBuffer


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a CBORHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """

    cons = False

    def __init__(self, stream: BaseBuf, frame: dict, console: bool | int = False):
        StackedBlk.__init__(self, stream, None)

        SerialPacker = __import__("serialpacker", globals(), None, ("SerialPacker",)).SerialPacker

        self.p = SerialPacker(**frame)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.w_lock = Lock()
        if console:
            _CReader.__init__(cast(_CReader, self), console)

    async def crd(self, buf: MutBuffer) -> int:
        "console read"
        if not self.cons:
            raise EOFError
        return await _CReader.crd(cast(_CReader, self), buf)

    async def cwr(self, buf) -> None:
        "console write"
        if not self.cons:
            return
        await self.s.wr(buf)

    async def rcv(self):
        "block read"
        while True:
            while self.i < self.n:
                msg = self.p.feed(self.buf[self.i])
                self.i += 1
                if isinstance(msg, int):
                    if self.cons:
                        _CReader.cput(cast(_CReader, self), msg)
                elif msg is not None:
                    return msg

            n = await self.s.rd(self.buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n

    async def snd(self, m: Buffer) -> None:
        "block write"
        h, msg, t = self.p.frame(m)
        async with self.w_lock:
            if not self.cons:
                await self.s.wr(h)
                await self.s.wr(msg)
                await self.s.wr(t)
            else:
                await self.s.wr(h + msg + t)

    recv = rcv
    send = snd


def serial_stack(stream, cfg: attrdict, cons: bool = False):
    """Build a message stack on top of a MoaT bytestream.

    This is a thin wrapper around :py:func:`moat.lib.stream.build_stack`
    that preserves the original calling convention.

    Configuration:
        link(dict):
            Link control; see below.
        log(dict):
            If present, log high-level messages.
        log(dict):
            If present, log messages
        log_raw(dict):
            If present, log the bytestream.

    Link control:
        cbor(bool):
            must be ``True``.
        lossy(bool):
            set if the stream is not 100% reliable.
        frame(int|dict):
            control protocol framing.
        console(bool):
            set if incoming non-framed data should be processed.

    If ``lossy`` is `True`, ``frame`` must be a dict.

    If ``frame`` is an integer, the protocol is assumed to be
    self-delimiting (e.g. CBOR). If it's a dict, the value is
    the configuration for a ``SerialPacker`` instance.

    There is no start-of-frame character escaping. Choose a value that cannot occur
    in an ASCII or possibly UTF-8 bytestream (≥ 0xF8).
    """
    if not hasattr(stream, "rd") or not hasattr(stream, "wr"):
        raise TypeError(f"need a BaseBuf not {stream}")

    return build_stack(stream, cfg, cons=cons)
