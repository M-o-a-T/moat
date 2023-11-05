"""
Basic BMS classes
"""
from __future__ import annotations

import sys

import time
from pprint import pprint
from moat.util import NotGiven, load_from_cfg, as_proxy, attrdict, val2pos
from moat.util.alert import Alert, AlertMixin
from moat.util.broadcast import Broadcaster

from moat.util.compat import (
    Event,
    TaskGroup,
    TimeoutError,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
    sleep,
)
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.array import ArrayCmd


class BatteryAlert(Alert):
    """
    For a given battery there will at most be one open alert of each type.
    """


@as_proxy("bms_SH", replace=True)
class HighSOC(BatteryAlert):
    "Charge exceeds limit"


@as_proxy("bms_SL", replace=True)
class LowSOC(BatteryAlert):
    "Charge below limit"


@as_proxy("bms_UH", replace=True)
class HighVoltage(BatteryAlert):
    "Total voltage exceeds limit"


@as_proxy("bms_UL", replace=True)
class LowVoltage(BatteryAlert):
    "Total voltage below limit"


@as_proxy("bms_CH", replace=True)
class HighCellVoltage(BatteryAlert):
    "Cell voltage exceeds limit"


@as_proxy("bms_CL", replace=True)
class LowCellVoltage(BatteryAlert):
    "Cell voltage below limit"


@as_proxy("bms_CI", replace=True)
class CellImbalance(BatteryAlert):
    "Excessive cell imbalance"


@as_proxy("bms_IH", replace=True)
class HighChargeCurrent(BatteryAlert):
    "Charge current exceeds limit"


@as_proxy("bms_IL", replace=True)
class HighDischargeCurrent(BatteryAlert):
    "Discharge current exceeds limit"


@as_proxy("bms_TH", replace=True)
class HighTemperature(BatteryAlert):
    "Temperature exceeds limit"


@as_proxy("bms_TL", replace=True)
class LowTemperature(BatteryAlert):
    "Temperature below operational limit"


@as_proxy("bms_NBD", replace=True)
class NoBatteryData(BatteryAlert):
    "no battery data seen"


@as_proxy("bms_NCD", replace=True)
class NoCellData(BatteryAlert):
    "no cell data seen"


@as_proxy("bms_VM", replace=True)
class VoltageDelta(BatteryAlert):
    "Battery and sum-of-cell voltages don't match"


class BaseCell(BaseCmd):
    """
    Skeleton for a single cell.

    Configuration::

        lim:
          u:
            abs:
              max: 3.65
              min: 2.55
            ext:
              max: 3.55
              min: 2.9
            std:
              max: 3.5
              min: 2.95
          t:
            abs:
              min: 0
              max: 45
            ext:
              min: 5
              max: 40
            std:
              min: 10
              max: 35
          bal:
            abs: 80
            ext: 70
            std: 60

    The limits are:

    * abs: exceed this and the relay triggers.
    * ext: outside of these the current limit is zero.
    * std: normal operation within this range

    The balancer doesn't have minimum temperatures.
    Comtrollers are free to implement more complicated curves.

    """
    async def cmd_u(self):
        "read cell voltage"
        raise NotImplementedError("no idea how")

    async def cmd_t(self):
        "read cell temperature"
        raise NotImplementedError("no idea how")

    async def cmd_tb(self):
        "read cell balancer temperature"
        raise NotImplementedError("no idea how")

    async def cmd_dis(self, v:float|None):
        """
        balance low: drain cell until below @v
        """
        raise NotImplementedError("no idea how")

    async def cmd_chg(self, v:float|None):
        """
        balance high: charge cell until above @v

        obviously this only works with an active balancer
        """
        raise NotImplementedError("no idea how")

    async def cmd_lim(self, soc:float = 0.5):
        """
        Limits (as fraction of C) depending on @soc, cell
        temperature, voltage, and whatnot.

        May raise an exception, in which case the relay should disengage.

        Otherwise, returns (chg,dis) factors to limit max cell charge/discharge.
        """
        u = await self.cmd_u()
        t = await self.cmd_t()

        lu = self.cfg["lim"]["u"]
        lt = self.cfg["lim"]["t"]

        if t is None:  # some cells might not have a sensor
            tf = 1
        else:
            if t > lt["abs"]["max"]:
                raise HighTemperature(t, self.path)
            if t < lt["abs"]["min"]:
                raise LowTemperature(t, self.path)

            tf = val2pos(lt["abs"]["max"],t,lt["ext"]["max"], clamp=True) * \
                val2pos(lt["abs"]["min"],t,lt["ext"]["min"], clamp=True)

        if u > lu["abs"]["max"]:
            raise HighCellVoltage(u, self.path)
        chg = tf * val2pos(lu["ext"]["max"],u,lu["std"]["max"], clamp=True)

        if u < lu["abs"]["min"]:
            raise LowCellVoltage(u, self.path)
        dis = tf * val2pos(lu["ext"]["min"],u,lu["std"]["min"], clamp=True)

        return (chg,dis)
        


class BaseCells(ArrayCmd):
    """
    Skeleton for a cell array.

    Basic configuration::

        apps:
          a: bms._test.Cells
        a:
          app: bms._test.Cell
          cfg: {}
          n: 8
          t:
            w: 500  # calculate energy

    """
    rly = None
    w:float = 0
    p:float = None

    def __init__(self, cfg):
        super().__init__(cfg)
        if "relay" in self.cfg:
            self.rly = self.root.sub_at(cfg["relay"])

    def cmd_tb(self) -> Awaitable:
        """fetch all cells' voltages"""
        return self.cmd_all("tb")

    async def cmd_su(self):
        """fetch voltage sum"""
        r = await self.cmd_u()
        return sum(r)

    async def cmd_lim(self):
        """return charge,discharge limit factors"""
        chg,dis = None,None
        try:
            for c,d in await self.cmd_all("lim"):
                if chg is None or chg > c:
                    chg = c
                if dis is None or dis > d:
                    dis = d
            return chg,dis

        except BatteryAlert:
            if self.rly is not None:
                await self.rly.w(v=False)
            raise

    async def _run_e(self):
        # calculate battery energy
        t1 = ticks_ms()
        i = await self.cmd_i()
        while True:
            await sleep_ms(self.cfg["t"]["w"]/2)
            u = await self.cmd_u()
            t2 = ticks_ms()
            self.p = p = i*u
            self.w += p * ticks_diff(t2,t1)
            u = await self.cmd_u()

            await sleep_ms(self.cfg["t"]["w"]/2)
            i = await self.cmd_i()
            t1 = ticks_ms()
            self.p = p = i*u
            self.w += p * ticks_diff(t2,t1)


    async def task(self):
        async with TaskGroup() as tg:
            await tg.spawn(self._run_e)
        pass


class BaseBattery(BaseCells):
    """
    Skeleton for a battery.
    """

    async def cmd_u(self):
        """fetch battery voltage"""
        raise RuntimeError

    async def cmd_i(self):
        """fetch battery current"""
        raise RuntimeError

    async def cmd_ud(self):
        """Get delta between cell voltage sum and battery voltage.
        """
        u1 = await self.cmd_u()
        u2 = sum(await self.all("u"))
        return u2-u1


class BaseBalancer:
    """
    Skeleton of a balancing controller

    Config::

        bat: !P r.x.bat
        n: 3  # max #cells to balance at the same time


    """

    def __init__(self, cfg: attrdict):
        self.cfg = cfg
        self.bat = self.root.sub_at(self.cfg["bat"])

    async def task(self):
        pass  # TODO


#class BasePower(MultiplyDict):
#    def __init__(self, cfg, bms):
#        super().__init__(cfg)
#        self.bms = bms
#        self.cfg = cfg
#        self.n = 0
#
#    async def task(self):
#        await every_ms(cfg.t, self.read)
#
#    async def read_(self):
#        res = await super().read_()
#        p = res["_"]
#        await self.bms.update_power(u=res["u"], i=res["i"], p=p)
#        return p
#
#    
#class BaseBattery:
#    """
#    This is the skeleton of a battery monitor client.
#
#    Alerts and updates are monitored.
#    """
#
#    cmd = None
#
#    ext_u: float = None  # last external voltage measurement
#    ext_i: float = None  # last external current measurement
#    ext_r: float = None  # wire resistance, to calculate ext/batt voltage delta
#
#    val_u: float = None  # voltage
#    val_i: float = None  # current
#    val_p: float = None  # momentary power
#    val_t: list[float] = None  # other temperatures
#    int_r: float = None  # internal resistance, whole battery
#
#    # required modules
#    cells: BaseCells = None
#    balancer: BaseBalancer = None
#    relay = None
#    power = None  # reader for voltage and current
#
#    sum_w: float = 0  # sum of u*i
#    sum_c: float = 0  # sum of i
#
#    _live_task = None
#    live: int = None  # required msec between pings
#    _main_task = None
#
#    def __init__(self, cfg):
#        pprint(cfg, sys.stderr)
#        self.cfg = cfg
#        self.xmit_evt = Event()
#        self.gen = 0  # generation, incremented every time a new value is read
#        self._q = Broadcaster()
#
#        super().__init__()
#
#    async def run(self, cmd):
#        """
#        Main loop. Runs the cell and balancer main code.
#        """
#        self.t_last = ticks_ms()
#
#        self.cmd = cmd
#        self.sum_w = 0
#        self.sum_c = 0
#        self.n_w = 0
#        self.live_flag = Event()
#
#        async with TaskGroup() as tg:
#            self.__tg = tg
#            self._main_task = await tg.spawn(self._run)
#            while True:
#                await sleep(9999)
#
#    async def update_power(
#        self, u: float, i: float, p: float = None, w: float = None, c: float = None
#    ):
#        self.val_u = u
#        self.val_i = i
#        self.val_p = u * i if p is None else p
#        if w is None or c is None:
#            t = ticks_ms()
#            td = ticks_diff(t, self.t_last)
#            self.t_last = t
#
#            if w is None:
#                self.val_w += td * self.val_p
#            else:
#                self.val_w = w
#
#            if c is None:
#                self.val_c += td * self.val_i
#            else:
#                self.val_c = c
#        await self.send_update("u_i")
#
#    async def _live(self):
#        while True:
#            await timeout_ms(self.live, self._live_evt.wait)
#            self._live_evt = Event()
#
#    async def set_live(self, t):
#        self.live = t
#        if not t:
#            if self._live_task is not None:
#                self._live_task.cancel()
#                self._live_task = None
#                self._live_evt = None
#        elif self._live_task is not None:
#            self._live_evt.set()
#        else:
#            self._live_evt = Event()
#            self._live_task = await self._tg.spawn(self._live)
#
#    async def live_ping(self):
#        if self._live_task is not None:
#            self._live_evt.set()
#
#    def stat(self, clear=False):
#        """
#        return current state + sums, optionally clear the sums
#        """
#        if self.relay is not None:
#            rs = self.relay.state()
#        else:
#            rs = {}
#
#        if self.live is not None:
#            rs["l"] = self.live
#
#        res = dict(
#            u=self.last_u,
#            i=self.last_i,
#            s=dict(w=self.sum_w, c=self.sum_c, n=self.n_w),
#            gen=self.gen,
#        )
#        if rs:
#            res["r"] = rs
#
#        if clear:
#            self.sum_w = 0
#            self.sum_c = 0
#            self.n_w = 0
#        return res
#
#    async def set_relay_force(self, st):
#        """
#        manually change the relay's state
#        """
#        if isinstance(self.relay, Listener):
#            await self.cmd.request.send([self.cmd.name, "rly"], st=st)
#        else:
#            self.relay_force = st
#            await self.relay.set(force=st)
#            await self.send_rly_state("forced")
#
#    async def live_state(self, live: bool):
#        """
#        is the system OK?
#        """
#        if self.live == live:
#            return
#        self.live = live
#        if not live and not isinstance(self.relay, Listener):
#            await self.relay.set(False)
#            await self.send_rly_state("Live Fail")
#
#    def set_live(self):
#        self.live_flag.set()
#
#    async def live_task(self):
#        while True:
#            try:
#                await wait_for_ms(self.cfg.poll.t.live, self.live_flag.wait)
#            except TimeoutError:
#                await self.live_state(False)
#            else:
#                self.live_flag = Event()
#                await self.live_state(True)
#
#    async def config_updated(self, cfg):
#        """
#        Kill it all off and restart.
#
#        TODO: try to be somewhat less intrusive.
#        """
#        if self._main_task is None:
#            self.cfg = cfg
#            return
#        self._main_task.cancel()
#        await sleep_ms(100)
#        self.cfg = cfg
#        self._main_task = await self.__tg.spawn(self._run)
#
#    async def send_work(self, flush: bool = False):
#        if not self.cmd:
#            return
#        res = dict(
#            w=self.sum_w,
#            c=self.sum_c,
#            n=self.n_w,
#            f=flush,
#        )
#        if flush:
#            self.sum_w = 0
#            self.sum_c = 0
#            self.n_w = 0
#        await self.cmd.request.send_nr([self.cmd.name, "work"], **res)
#
#    async def _run(self):
#        async with TaskGroup() as tg:
#            cfg = self.cfg
#            try:
#                self.cells = load_from_cfg(cfg.cells, bms=self)
#            except AttributeError:
#                breakpoint()
#                raise
#            self.balancer = load_from_cfg(cfg.balancer, cells=self.cells)
#            self.relay = load_from_cfg(cfg.relay, bms=self, _raise=True)
#            self.power = load_from_cfg(cfg.power, bms=self)
#
#            if self.relay is not None:
#                tg.start_soon(self.relay.run, self.cmd)
#            if self.cells is not None:
#                tg.start_soon(self.cells.run, self.cmd)
#            if self.balancer is not None:
#                tg.start_soon(self.balancer.run, self.cmd)
#            if self.power is not None:
#                tg.start_soon(self.power.run, self.cmd)
#
#            await tg.spawn(self.live_task, _name="bms.live")
#            await self._run_()
#
#    async def _run_(self):
#        xmit_n = 0
#        self.live = (await self.relay.read())["s"]
#        # we start off with the current relay state
#        # so a soft reboot won't toggle the relay
#
#        self.t = ticks_ms()
#
#        while True:
#            self.t = ticks_add(self.t, self.cfg.poll.t.voltage)
#
#            if self.live:
#                rs = self.relay.get_sync()
#
#                if await self._check():
#                    await self.relay.set(True)
#                else:
#                    await self.relay.set(False)
#
#                if rs != self.relay.get_sync():
#                    if rs:
#                        await self.send_rly_state("Check OK")
#                    else:
#                        await self.send_rly_state("Check Fail")
#                    xmit_n = 0
#
#            xmit_n -= 1
#            if xmit_n <= 0 or self.xmit_evt.is_set():
#                if self.gen >= 99:
#                    self.gen = 10
#                else:
#                    self.gen += 1
#                self.xmit_evt.set()
#                self.xmit_evt = Event()
#                xmit_n = self.cfg.poll.n.voltage
#
#            t = ticks_ms()
#            td = ticks_diff(self.t, t)
#            if td > 0:
#                if self.n_w >= 10000:
#                    await self.send_work()
#                await sleep_ms(td)
#            else:
#                self.t = t
#
#    async def send_rly_state(self, txt):
#        self.xmit_evt.set()
#        print("RELAY", (await self.relay.read()), txt, file=sys.stderr)
#
#
#class BaseBMSCmd(BaseCmd):
#    def __init__(self, parent: BaseCmd, name: str, cfg: attrdict, gcfg: attrdict):
#        super().__init__(parent)
#        self.name = name
#        self.batt = None
#        self.bms = load_from_cfg(cfg)
#        if self.bms is None:
#            raise ImportError(cfg)
#
#    async def run(self):
#        try:
#            await self.bms.run(self)
#        finally:
#            self.bms = None
#
#    async def config_updated(self, cfg):
#        await super().config_updated(cfg)
#        await self.bms.config_updated(cfg)
#
#    async def cmd_rly(self, st=NotGiven):
#        """
#        Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
#        """
#        rly = self.batt.relay
#        if rly is None:
#            raise RuntimeError("no relay")
#        if st is NotGiven:
#            return rly.state()
#        await rly.set(force=st)
#
#    async def cmd_info(self, gen=-1, r=False):
#        if self.batt.gen == gen:
#            await self.batt.xmit_evt.wait()
#        return self.batt.stat(r)
#
#    async def cmd_live(self, t=None):
#        """
#        Keepalive. Set t=x to require a call every t seconds.
#        t=0 disables. No t is the ping.
#        """
#        if t is None:
#            self.batt.ping()
#        else:
#            await self.batt.set_live(t)
