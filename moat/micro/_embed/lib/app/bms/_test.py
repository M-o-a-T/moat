"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import random
import logging
import sys
from math import exp
from functools import partial

from moat.util.compat import TaskGroup, sleep_ms, Event
from moat.util import pos2val,val2pos,attrdict
from moat.micro.compat import ticks_ms, Queue
from moat.micro.cmd.array import ArrayCmd
from moat.micro.cmd.base import BaseCmd

from moat.ems.battery._base import BaseCell, BaseBattery, BaseBalancer
from moat.ems.battery.diy_serial.packet import PacketHeader,PacketType,replyClass
from moat.ems.battery.diy_serial.packet import ReplyIdentify

logger = logging.getLogger(__name__)

class Cell(BaseCell):
    """
    Mock battery cell.

    Its nominal charge is 0…1, capacity in amp-sec.

    The voltages are linear between u.ext, plus a power term when exceeding
    that.

    A configuration that replicates a LiFePo4 cell, *very* approximately::

        c: 0.5
        t: 25
        cap: 2000
        i:
          dis: -1  # balancer discharge current
          chg: 0  # TODO
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
            std:
              min: 2.6
              max: 3.55
            ext:
              min: 2.9
              max: 3.4
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self._c = cfg["c"]
        self._t = cfg["t"]
        self._tb = 25
        self.t_env = 25
    
    async def set_dis(self):
        "set discharger. No-op since we can use .vdis directly."
        pass

    async def cmd_c(self, c:float|None=None) -> float:
        "get/set the current charge"
        if c is not None:
            self._c = c
        return self._c

    async def cmd_u(self, c:float|None=None) -> float:
        """
        return the current voltage.

        If @c is set, return the voltage the cell would have if its current charge was c.
        """
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

    async def cmd_te(self, t=None) -> float:
        "gets/sets the environment temperature"
        if t is None:
            return self.t_env
        self.t_env = t

    async def cmd_t(self):
        "returns the balancer resistor temperature"
        return self._t

    async def cmd_tb(self):
        "returns the battery temperature"
        return self._tb

    async def cmd_add_p(self, p, t):
        "add power to the battery: @p watts for @t msec"
        # watt seconds
        self._c += p*t/self.cfg["cap"]/1000

        # time takes heat away, Charge+Discharge adds it
        self._t += (self.t_env-self._t)*(1-exp(-t/10000)) + abs(p)*t/100000*(1 if p>0 else 0.5)

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


class _CellSim(BaseCmd):
    # needs "ctrl" and "cell" attributes
    ctrl=None
    cell=None

    async def task(self):
        while True:
            msg = await self.ctrl.xrb()
            hdr,msg = PacketHeader.decode(msg)
            addr = hdr.hops
            hdr.hops += 1
            if hdr.start > addr or hdr.start+hdr.cells < addr:
                # not for us
                await self.ctrl.xsb(m=hdr.encode_one(msg))
                continue

            hdr.seen = True

            pkt,msg = hdr.decode_one(msg)
            logger.debug("MSG %r %r",hdr,pkt)
            rsp = replyClass[hdr.command]()
            if hdr.command == PacketType.ResetPacketCounters:
                pass
            elif hdr.command == PacketType.ReadVoltageAndStatus:
                pass
            elif hdr.command == PacketType.Identify:
                pass
            elif hdr.command == PacketType.ReadTemperature:
                pass
            elif hdr.command == PacketType.ReadPacketCounters:
                pass
            elif hdr.command == PacketType.ReadSettings:
                pass
            elif hdr.command == PacketType.WriteSettings:
                pass
            elif hdr.command == PacketType.ReadBalancePowerPWM:
                pass
            elif hdr.command == PacketType.Timing:
                rsp.timer = pkt.timer
            elif hdr.command == PacketType.ReadBalanceCurrentCounter:
                pass
            elif hdr.command == PacketType.ResetBalanceCurrentCounter:
                pass
            elif hdr.command == PacketType.WriteBalanceLevel:
                pass
            elif hdr.command == PacketType.WritePIDconfig:
                pass
            elif hdr.command == PacketType.ReadPIDconfig:
                pass
            else:
                logger.warning("Not answering %r", msg)
                continue

            await self.ctrl.xsb(m=hdr.encode_one(msg, rsp))

class CellSim(_CellSim):
    """
    Back-end to simulate a single cell.

    This is a background app. It reads byte blocks from the loopback app at @ctrl,
    analyzes them, and replies according to the cell app at @cell.
    """
    async def setup(self):
        await super().setup()
        self.cell = self.root.sub_at(*self.cfg["cell"])
        self.ctrl = self.root.sub_at(*self.cfg["ctrl"])

    async def task(self):
        self.set_ready()
        await super().task()


class _SingleCellSim(_CellSim):
    """
    Interface for a cell in a series, configured via CellsSim.
    """
    def __init__(self, cell, ctrl):
        self.cell = cell
        self.ctrl = ctrl


class CellsSim(_CellSim):
    """
    Back-end to simulate multiple cells.

    Config:
        n: number of cells
        ctrl: LoopLink taking to them
        cell: path to the array of Cell objects this app shall control
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self.n_cells = cfg["n"]

    async def setup(self):
        await super().setup()
        self.ctrl = self.root.sub_at(*self.cfg["ctrl"])

    async def task(self):
        cell = self.cfg["cell"]

        def _mput(q, m):
            return q(m)

        async with TaskGroup() as tg:
            q = None
            for i in range(self.n_cells):
                c = attrdict()
                if i == 0:  # first
                    c.xrb = self.ctrl.xrb
                else:
                    c.xrb = q.get
                if i < self.n_cells-1:
                    q = Queue()
                    c.xsb = partial(_mput, q.put)
                else:  # last
                    c.xsb = self.ctrl.xsb

                cp = self.root.sub_at(*cell, i)
                sim = _SingleCellSim(cp, c)
                await tg.spawn(sim.task)
            self.set_ready()


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

###

def etb(self):
    return b""
ReplyIdentify.to_bytes=etb
