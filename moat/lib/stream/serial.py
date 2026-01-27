"""
SerialPacker protocol support for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import Lock
from moat.lib.stream import BaseBuf, BaseMsg, StackedBlk

from ._console import _CReader

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict


class SerialPackerBlkBuf(StackedBlk):
    """
    chunked bytestrings > SerialPacker-ized stream

    Use this (and a CBORHandler and a Reliable) if your AIO stream
    is unreliable (TTL serial).
    """

    cons = False

    def __init__(self, stream: BaseBuf, frame: dict, console: bool | int = False):
        super().__init__(None)

        from serialpacker import SerialPacker  # noqa: PLC0415

        self.s = stream
        self.p = SerialPacker(**frame)
        self.buf = bytearray(16)
        self.i = 0
        self.n = 0
        self.w_lock = Lock()
        if console:
            _CReader.__init__(self, console)

    async def crd(self, buf):
        "console read"
        if not self.cons:
            raise EOFError
        return await _CReader.crd(self, buf)

    async def cwr(self, buf):
        "console write"
        if not self.cons:
            return
        return await super().wr(buf)

    async def recv(self):
        "block read"
        while True:
            while self.i < self.n:
                msg = self.p.feed(self.buf[self.i])
                self.i += 1
                if isinstance(msg, int):
                    if self.cons:
                        _CReader.cput(self, msg)
                elif msg is not None:
                    return msg

            n = await self.s.rd(self.buf)
            if not n:
                raise EOFError
            self.i = 0
            self.n = n

    async def send(self, msg):
        "block write"
        h, msg, t = self.p.frame(msg)
        async with self.w_lock:
            if not self.cons:
                await self.s.wr(h)
                await self.s.wr(msg)
                await self.s.wr(t)
            else:
                await self.s.wr(h + msg + t)


def serial_stack(stream, cfg: attrdict, cons: bool = False):
    # lossy=False, log=False, use_console=False, msg_prefix=None
    """
    Build a message stack on top of a MoaT bytestream.

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

    link = cfg.get("link", {})
    cons = link.get("console", cons)
    frame = link.get("frame", None)
    lossy = link.get("lossy", None)
    log = cfg.get("log", None)
    log_raw = cfg.get("log_raw", None)
    log_rel = cfg.get("log_rel", None)

    if log_raw is not None:
        from moat.lib.stream import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log_raw)

    if isinstance(frame, dict):
        from moat.lib.stream import CBORMsgBlk  # noqa: PLC0415

        stream = SerialPackerBlkBuf(stream, frame=frame, console=cons)
        stream = CBORMsgBlk(stream, cfg)
    else:
        from moat.lib.stream import CBORMsgBuf  # noqa: PLC0415

        stream = CBORMsgBuf(stream, dict(msg_prefix=frame, console=cons))

    assert isinstance(stream, BaseMsg)

    if lossy:
        if lossy is True:
            lossy = {}
        from moat.lib.stream import ReliableMsg  # noqa: PLC0415

        if log_rel is not None:
            from moat.lib.stream import LogMsg  # noqa: PLC0415

            stream = LogMsg(stream, log_rel)

        stream = ReliableMsg(stream, lossy)

    if log is not None:
        from moat.lib.stream import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log)

    return stream
