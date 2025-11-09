"""
TMP102 i²c
"""

from __future__ import annotations

import struct

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import sleep_ms

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


class Cmd(BaseCmd):
    """
    This is the front-end for a TMP102 i²c temperature sensor.

    Config:
        bus: Path to the bus to use
        adr: Bus address to access
    """

    async def run(self):
        "wrapper, for i2c bus access"
        self.adr = self.cfg.adr
        async with self.root.sub_at(self.cfg.bus) as self.bus:
            await super().run()

    doc_r = dict(
        _d="read",
        t="int:ms between reads when streaming, default 10s",
        o="bool:old: wait until value differs",
    )

    async def _rd(self):
        await self.bus.wr(self.adr, bytes((1, 0x81, 0x10)))
        # OneShot+Shutdown, Extended
        for _ in range(10):
            await sleep_ms(3)
            res = await self.bus.wrrd(self.adr, bytes((1,)), 2)
            if res[0] & 0x80:
                break
        else:
            raise RuntimeError("No conv")
        res = await self.bus.wrrd(self.adr, bytes((0,)), 2)
        (t,) = struct.unpack(">h", res)
        assert t & 1, (res, t)
        t -= 1
        return t

    async def stream_r(self, msg: Msg):
        "Wait for change if @o (old value) is not None"
        t = msg.get("t", 10000)
        o = msg.get("o", None)
        if o is not None:
            o = int(o * 128)
        d = int(msg.get("d", 0) * 128)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    val = await self._rd()
                    if o is None or abs(val - o) > d:
                        await m.send(val / 128)
                        if o is not None:
                            o = val
                    await sleep_ms(t)

        val = await self._rd()
        while o is not None and abs(val - o) <= d:
            await sleep_ms(t)
            val = await self._rd()
        await msg.result(val / 128)
