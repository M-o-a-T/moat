"""
CBOR message encoding/decoding for stream layers.
"""

from __future__ import annotations

from moat.lib.micro import AC_use, Lock, log
from moat.lib.stream import BaseBuf, StackedMsg

from ._console import _CReader

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.codec import Codec
    from moat.util.liner import Liner

    from collections.abc import Awaitable
    from typing import Any


class _CBORMsgBuf(StackedMsg):
    """
    structured messages > CBOR bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.

    If @console is set and a prefix is used, sends data atomically.
    Otherwise two separate write calls are used to save on message copying.

    Config:
        console (bool):
            Flag how to handle non-framed data.
            True: collect for crd/cwr, False: print incoming, None: ignore.
        msg_prefix(int):
            bytecode of prefix for messages (as opposed to console data)
    """

    cons = False
    codec: Codec = None
    liner: Liner = None

    def __init__(self, stream: BaseBuf, cfg: dict):
        #
        # console: size of console buffer, 128 if True
        # msg_prefix: int: code for start-of-packet
        #
        super().__init__(stream, cfg)
        self.w_lock = Lock()

        pref = cfg.get("msg_prefix")
        if pref is not None:
            pref = bytes((pref,))
        self.pref = pref

        cons = cfg.get("console", False)
        if cons:
            _CReader.__init__(self, cons)

    async def setup(self):
        await super().setup()
        if self.cons is False:
            from moat.util.liner import Liner  # noqa:PLC0415

            self.liner = await AC_use(self, Liner())

    async def cwr(self, buf):
        if not self.cons:
            return
        return await self.s.wr(buf)

    def crd(self, buf) -> Awaitable:
        return _CReader.crd(self, buf)

    async def send(self, msg: Any) -> None:
        try:
            msg = self.codec.encode(msg)
        except Exception:
            log("MSG:\n%r", msg)
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

        buf = bytearray(64)
        if self.pref is None:
            # easy case
            while True:
                try:
                    r = next(self.codec)
                except StopIteration:
                    n = await self.s.rd(buf)
                    self.codec.feed(memoryview(buf)[:n])
                else:
                    if self.cons and isinstance(r, int) and r >= 0:
                        _CReader.cput(self, r)
                    else:
                        return r

        while True:
            b = bytearray(1)
            # read until we get a prefix byte
            if self.codec.unfeed(b) == 0:
                n = await self.s.rd(buf)
                self.codec.feed(memoryview(buf)[:n])
            elif b == self.pref:
                break
            elif self.cons:
                _CReader.cput(self, b[0])
            elif self.liner is not None:
                self.liner(b)

        while True:
            # read until we get an object
            try:
                return next(self.codec)
            except StopIteration:
                pass

            n = await self.s.rd(buf)
            self.codec.feed(memoryview(buf)[:n])


class _CBORMsgBlk(StackedMsg):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def send(self, msg):
        await self.s.snd(self.codec.encode(msg))

    async def recv(self):
        m = await self.s.rcv()
        return self.codec.decode(m)
