"""
TMP102 i²c sensor
"""

from __future__ import annotations

import struct

from moat.lib.micro import sleep_ms
from moat.micro.util import Sensor

__all__ = ["Cmd"]


class Cmd(Sensor):
    """
    This is the front-end for a TMP102 i²c temperature sensor.

    Config:
        bus: Path to the bus to use
        adr: Bus address to access
    """

    doc = Sensor.doc.copy()
    doc["_c"] = doc["_c"].copy()
    doc["_c"]["bus"] = "path:i2c bus"
    doc["_c"]["adr"] = "path:bus address"

    async def task(self):
        "wrapper, for i2c bus access"
        self.adr = self.cfg["adr"]
        async with self.root.sub_at(self.cfg["bus"]) as self.bus:
            await super().task()

    async def read(self):
        "read sensor"
        await self.bus.wr(self.adr, bytes((1, 0x81, 0x10)))
        # OneShot+Shutdown, Extended
        for _ in range(20):
            await sleep_ms(3)
            res = await self.bus.wrrd(self.adr, bytes((1,)), 2)
            if res[0] & 0x80:
                break
        else:
            raise RuntimeError("No conv")
        res = await self.bus.wrrd(self.adr, bytes((0,)), 2)

        (t,) = struct.unpack(">h", res)
        if not (t & 1):
            raise ValueError(t)
        t -= 1
        return t / 128
