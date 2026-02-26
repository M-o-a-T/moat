"""
CBOR message encoding/decoding for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import AC_use, Lock, log
from moat.lib.stream import BaseBuf, StackedMsg

from ._console import _CReader

from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from moat.lib.codec import Codec
    from moat.util.liner import Liner

    from typing import Any

    MutBuf = bytes | bytearray | memoryview


class _CBORMsgBuf(StackedMsg):
    """
    structured messages > CBOR bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.

    If @console is set and a prefix is used, sends data atomically.
    Otherwise two separate write calls are used to save on message copying.

    Config:
        console:
            Flag how to handle non-framed data.
            True: collect for crd/cwr, False: print incoming, None: ignore.
            If an integer: Buffer size
        msg_prefix:
            value of the prefix byte for messages (as opposed to console data).

    :meta public:
    """

    cons: bool | int = False
    codec: Codec | None = None
    liner: Liner | None = None

    def __init__(self, stream: BaseBuf, cfg: dict):
        StackedMsg.__init__(self, stream, cfg)
        self.w_lock = Lock()

        pref = cfg.get("msg_prefix")
        if pref is not None:
            pref = bytes((pref,))
        self.pref = pref

        cons = cfg.get("console", False)
        if cons:
            _CReader.__init__(cast("Any", self), cons)

    async def setup(self):
        await super().setup()
        if self.cons is False:
            from moat.util.liner import Liner  # noqa:PLC0415

            self.liner = await AC_use(self, Liner())

    async def cwr(self, buf: MutBuf) -> None:
        if not self.cons:
            return
        await self.s.wr(buf)

    async def crd(self, buf: MutBuf) -> int:
        if not isinstance(buf, bytearray):
            raise TypeError("Need a bytearray")
        return await _CReader.crd(cast("Any", self), buf)

    async def send(self, m: Any) -> Any:
        codec = self.codec
        if codec is None:
            raise RuntimeError("No codec")
        try:
            msg = codec.encode(m)
        except Exception:
            log("MSG:\n%r", m)
            raise
        async with self.w_lock:
            if self.pref is not None:
                if True:  # self.cons:
                    msg = self.pref + msg  # must be atomic
                else:
                    await self.s.wr(self.pref)
            await self.s.wr(msg)

    async def recv(self) -> Any:
        """
        Receive the next object.
        """
        # Pre+postcondition: the codec does not have an object in progress.

        codec = self.codec
        if codec is None:
            raise RuntimeError("No codec")
        buf = bytearray(64)
        if self.pref is None:
            # easy case
            while True:
                try:
                    r = next(codec)
                except StopIteration:
                    n = await self.s.rd(buf)
                    codec.feed(memoryview(buf)[:n])
                else:
                    if self.cons and isinstance(r, int) and r >= 0:
                        _CReader.cput(cast("Any", self), r)
                    else:
                        return r

        while True:
            b = bytearray(1)
            # read until we get a prefix byte
            if codec.unfeed(b) == 0:
                n = await self.s.rd(buf)
                codec.feed(memoryview(buf)[:n])
            elif b == self.pref:
                break
            elif self.cons:
                _CReader.cput(cast("Any", self), b[0])
            elif self.liner is not None:
                self.liner(bytes(b))

        while True:
            # read until we get an object
            try:
                return next(codec)
            except StopIteration:
                pass

            n = await self.s.rd(buf)
            codec.feed(memoryview(buf)[:n])


class _CBORMsgBlk(StackedMsg):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).

    :meta public:
    """

    codec: Codec | None = None

    async def send(self, m: Any) -> Any:
        codec = self.codec
        if codec is None:
            raise RuntimeError("No codec")
        await self.s.snd(codec.encode(m))

    async def recv(self):
        codec = self.codec
        if codec is None:
            raise RuntimeError("No codec")
        m = await self.s.rcv()
        return codec.decode(m)
