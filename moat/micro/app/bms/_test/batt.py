"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import logging
import random

from moat.ems.battery._base import BaseBalancer, BaseBattery
from moat.util.compat import sleep_ms

logger = logging.getLogger(__name__)


class Batt(BaseBattery):
    """
    A fake battery.

    Additional Config::
        n: 4  # number of cells
        cfg: {}  # add
        rnd: 0.1  # random factor for add_p, here 0.9…1.1


    """

    u_d: float = 1.01
    i: float = 0

    def __init__(self, cfg):
        super().__init__(cfg)
        self._rand = random.Random()

    def _random(self, r=1):
        "random number between 0 and @r"
        return self._rand.random() * r

    doc_u = dict(_d="read u", _r="float:voltage")

    async def cmd_u(self):
        "return synthetic voltage, multiplied by u_d"
        return self.u_d * await super().cmd_u()

    doc_u_d = dict(_d="write u delta", ud="float:voltage delta")

    async def cmd_u_d(self, *, ud: float):
        "change delta of battery vs. sum-of-cells voltage"
        self.u_d = ud

    doc_c = dict(_d="read charge state", _r="float")

    async def cmd_c(self):
        r = 0
        for c in self.apps:
            r += await c.cmd_c()
        return r / self.n

    doc_i = dict(_d="read current", _r="float")

    async def cmd_i(self, i: float | None = None):
        if i is not None:
            self.i = i
        return self.i

    async def feed_energy(self):
        s = 100  # ms per loop
        while True:
            await sleep_ms(s)
            p = (await self.cmd_u()) * (await self.cmd_i())

            r = self.cfg.get("rnd", 0)
            u = await self.cmd_u()
            for c in self.apps:
                f = (await c.cmd_u()) / u
                rnd = 1 + self._random(r * 2) - r if r > 0 else 1
                await c.cmd_add_p(p=p * f * rnd, t=s)

    async def start_tasks(self, tg):
        await super().start_tasks(tg)
        await tg.spawn(self.feed_energy)


class Bal(BaseBalancer):
    """
    Balancer support for a battery.
    """

    pass
