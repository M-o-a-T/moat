"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import random
import logging
import sys

from moat.util.compat import TaskGroup, sleep_ms, Event
from moat.util import pos2val,val2pos
from moat.micro.compat import ticks_ms
from moat.micro.cmd.array import ArrayCmd
from moat.micro.cmd.base import BaseCmd

from moat.ems.battery._base import BaseCell, BaseBattery, BaseBalancer
from moat.ems.battery.diy_serial.packet import PacketHeader,PacketType
from moat.ems.battery.diy_serial.packet import ReplyTiming

logger = logging.getLogger(__name__)

class Cell(BaseCell):
    """
    Mock battery cell.

    Its nominal charge is 0…1, capacity in amp-sec.

    The voltages are linear between u.ext, plus a power term when exceeding
    that.

    Config::

        c: 0.5
        cap: 2000
        lim:
          t:
            abs:
              min: 0
              max: 45
            ext:
              min: 10
              max: 40
          c:
            min: 0.2
            max: 0.9
          p:  # exponent when 'ext' limit is exceeded
            min: 2
            max: 3
          u:
            abs:
              min: 2.5
              max: 3.65
            ext:
              min: 2.9
              max: 3.4
          i:
            dis: -1  # balancer discharge current
            chg: 0
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self._c = cfg["c"]
        self._t = cfg["t"]
        self._tb = 25
    
    async def set_dis(self):
        "set discharger. No-op since we can use .vdis directly."
        pass

    async def cmd_c(self, c:float|None=None) -> float:
        if c is not None:
            self._c = c
        return self._c

    async def cmd_u(self, c:float|None=None):
        li = self.cfg["lim"]
        liu = li["u"]
        if c is None:
            c = self._c
        up = val2pos(li["c"]["min"],c,li["c"]["max"])
        if up < 0:
            fx = val2pos(li["c"]["min"],c,0) ** li["p"]["min"]
            u = pos2val(liu["ext"]["min"],fx,liu["abs"]["min"])
        elif up > 1:
            fx = val2pos(li["c"]["max"],c,1) ** li["p"]["max"]
            u = pos2val(liu["ext"]["max"],fx,liu["abs"]["max"])
        else:
            u = pos2val(liu["ext"]["min"],up,liu["ext"]["max"])
        return u

    async def cmd_t(self):
        return self._t

    async def cmd_tb(self):
        return self._tb

    async def cmd_add_p(self, p, t):
        "add power to the battery: @p watts for @t msec"
        # watt seconds
        self._c += p*t/self.cfg["cap"]/1000

        # incoming power adds heat to the battery
        self._t += (25-self._t)*0.01 + abs(p)*t/100000

    async def task(self):
        self.set_ready()

        while True:
            await sleep_ms(100)
            if self.vdis:
                u = await self.cmd_u()
                if u > self.vdis:
                    await self.cmd_add_p(u*self.cfg["i"]["dis"], 100)

            if self.vchg:
                u = await self.cmd_u()
                if u < self.vchg:
                    await self.cmd_add_p(u*self.cfg["i"]["chg"], 100)


class CellSim(BaseCmd):
    async def setup(self):
        await super().setup()
        self.cell = self.root.sub_at(*self.cfg["cell"])
        self.ctrl = self.root.sub_at(*self.cfg["ctrl"])

    async def task(self):
        self.set_ready()
        while True:
            msg = await self.ctrl.xrb()
            hdr,msg = PacketHeader.decode(msg)
            addr = hdr.hops
            hdr.hops += 1
            if hdr.start > addr or hdr.start+hdr.cells < addr:
                # not for us
                await self.ctrl.xsb(m=hdr.encode(msg))
                continue

            hdr.seen = True

            pkt,msg = hdr.decode_one(msg)
            logger.debug("MSG %r %r",hdr,pkt)
            rsp = None
            if hdr.command == PacketType.Timing:
                rsp = ReplyTiming(timer=ticks_ms())
            else:
                logger.warning("Not answering %r", msg)
                continue

            await self.ctrl.xsb(m=hdr.encode_one(msg, rsp))




class Batt(BaseBattery):
    """
    A fake battery.

    Additional Config::
        n: 4  # number of cells
        cfg: {}  # add 
        rnd: 0.1  # random factor for add_p, here 0.9…1.1

    
    """
    u_d:float = 1.01
    i:float = 0

    def __init__(self,cfg):
        super().__init__(cfg)
        self._rand = random.Random()

    def _random(self, r=1):
        "random number between 0 and @r"
        return self._rand.random() * r

    async def cmd_u(self):
        "return synthetic voltage, multiplied by u_d"
        return self.u_d * await super().cmd_u()

    async def cmd_u_d(self, *, ud:float):
        "change delta of battery vs. sum-of-cells voltage"
        self.u_d = ud

    async def cmd_c(self):
        r = 0
        for c in self.apps:
            r += await c.cmd_c()
        return r / self.n

    async def cmd_i(self, i:float=None):
        if i is not None:
            self.i = i
        return self.i

    async def feed_energy(self):
        s = 100  # ms per loop
        while True:
            await sleep_ms(s)
            p = (await self.cmd_u()) * (await self.cmd_i())
        
            r=self.cfg.get("rnd",0)
            u=await self.cmd_u()
            for c in self.apps:
                f=(await c.cmd_u())/u
                rnd=1+self._random(r*2)-r if r>0 else 1
                await c.cmd_add_p(p=p*f*rnd,t=s)

    async def start_tasks(self, tg):
        await super().start_tasks(tg)
        await tg.spawn(self.feed_energy)


class Bal(BaseBalancer):
    """
    Balancer support for a battery.
    """
    pass
