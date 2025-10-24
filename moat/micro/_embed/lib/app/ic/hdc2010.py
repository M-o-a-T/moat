"""
HDC2010 i²c
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
    This is the front-end for a HDC2010 i²c temperature+humidity sensor.

    Config:
        bus: Path to the bus to use
        adr: Bus address to access
    """

    async def run(self):
        "wrapper, for i2c bus access"
        self.adr = self.cfg.adr
        async with self.root.sub_at(self.cfg["bus"]) as self.bus:
            await super().run()

    doc_r = dict(
        _d="read",
        t="int:ms between reads when streaming, default 10s",
        o="bool:old: wait until value differs",
    )

    async def _rdt(self):
        await self.bus.wr(self.adr, bytes((15, 0x01)))
        # OneShot+Shutdown, Extended
        for _ in range(10):
            await sleep_ms(3)
            res = await self.bus.wrrd(self.adr, bytes((4,)), 1)
            if res[0] & 0x80:
                break
        else:
            raise RuntimeError("No conv")
        res = await self.bus.wrrd(self.adr, bytes((0,)), 2)
        (t,) = struct.unpack("<h", res)
        return t

    async def stream_rt(self, msg: Msg):
        "Wait for change if @o (old value) is not None"
        t = msg.get("t", 10000)
        o = msg.get("o", None)
        if o is not None:
            o = int((o + 40) * 65536 / 165)
        d = int(msg.get("d", 0) * 65536 / 165)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    val = await self._rdt()
                    if o is None or abs(val - o) > d:
                        await m.send(val * 165 / 65536 - 40)
                        if o is not None:
                            o = val
                    await sleep_ms(t)

        val = await self._rdt()
        while o is not None and abs(val - o) <= d:
            await sleep_ms(t)
            val = await self._rdt()
        await msg.result(val * 165 / 65536 - 40)

    async def _rdh(self):
        await self.bus.wr(self.adr, bytes((15, 0x01)))
        # OneShot+Shutdown, Extended
        for _ in range(10):
            await sleep_ms(3)
            res = await self.bus.wrrd(self.adr, bytes((4,)), 1)
            if res[0] & 0x80:
                break
        else:
            raise RuntimeError("No conv")
        res = await self.bus.wrrd(self.adr, bytes((2,)), 2)
        (h,) = struct.unpack("<h", res)
        return h

    async def stream_rh(self, msg: Msg):
        "Wait for change if @o (old value) is not None"
        t = msg.get("t", 10000)
        o = msg.get("o", None)
        if o is not None:
            o = int(o * 65536 / 100)
        d = int(msg.get("d", 0) * 65536 / 100)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    val = await self._rdh()
                    if o is None or abs(val - o) > d:
                        await m.send(val * 100 / 65536)
                        if o is not None:
                            o = val
                    await sleep_ms(t)

        val = await self._rdh()
        while o is not None and abs(val - o) <= d:
            await sleep_ms(t)
            val = await self._rdh()
        await msg.result(val * 100 / 65536)

    async def _rdth(self):
        await self.bus.wr(self.adr, bytes((15, 0x01)))
        # OneShot+Shutdown, Extended
        for _ in range(10):
            await sleep_ms(3)
            res = await self.bus.wrrd(self.adr, bytes((4,)), 1)
            if res[0] & 0x80:
                break
        else:
            raise RuntimeError("No conv")
        res = await self.bus.wrrd(self.adr, bytes((0,)), 4)
        (t, h) = struct.unpack("<hh", res)
        return t, h

    async def stream_rth(self, msg: Msg):
        "Wait for change if @o (old value) is not None"
        t = msg.get("t", 10000)
        ot = msg.get("ot", None)
        if ot is not None:
            ot = int((ot + 40) * 65536 / 165)
        oh = msg.get("oh", None)
        if oh is not None:
            oh = int(oh * 65536 / 100)
        dt = int(msg.get("d", 0) * 65536 / 165)
        dh = int(msg.get("d", 0) * 65536 / 100)
        if msg.can_stream:
            async with msg.stream_out() as m:
                while True:
                    t, h = await self._rdth()
                    if ot is None or oh is None or abs(t - ot) > dt or abs(h - oh) > dh:
                        await m.send(t * 165 / 65536 - 40, h * 100 / 65536)
                        if ot is not None:
                            ot = t
                        if oh is not None:
                            oh = h
                    await sleep_ms(t)

        t, h = await self._rdth()
        while ot is not None and oh is not None and abs(t - ot) <= dt and abs(h - oh) <= dh:
            await sleep_ms(t)
            t, h = await self._rdth()
        await msg.result(t * 165 / 65536 - 40, h * 100 / 65536)
