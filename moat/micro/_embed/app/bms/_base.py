"""
Basic BMS classes
"""

import sys

import time
from moat.util import NotGiven, load_from_cfg, as_proxy, attrdict
from moat.util import Alert, AlertMixin, Broadcaster

from moat.micro.cmd import BaseCmd
from moat.micro.compat import (
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


class BaseCells:
    """
    Skeleton of a cell array.
    """

    n_cells = None

    def __init__(self, cfg):
        self.cfg = cfg

    async def read_u(self):
        """fetch all cells' voltages"""
        raise NotImplementedError("no idea how")

    async def read_t(self):
        """fetch all cells' temperatures"""
        raise NotImplementedError("no idea how")

    async def run(self, cmd, batt):
        pass


class BaseBalancer:
    """
    Skeleton of a balancing controller
    """

    def __init__(self, cells: BaseCells, cfg: attrdict):
        self.cells = cells
        self.cfg = cfg

    async def run(self, cmd, cells):
        pass  # TODO


class BasePower(moat.micro.part.combo.MultiplyDict):
    def __init__(self, cfg, bms):
        super().__init__(cfg)
        self.bms = bms
        self.cfg = cfg
        self.n = 0

    async def run(self):
        await every_ms(cfg.t, self.read)

    async def read_(self):
        res = await super().read_()
        p = res["_"]
        await self.bms.update_power(u=res["u"], i=res["i"], p=p)
        return p

    
class BaseBattery(AlertMixin):
    """
    This is the skeleton of a battery monitor client.

    Alerts and updates are monitored.
    """

    cmd = None

    ext_u: float = None  # last external voltage measurement
    ext_i: float = None  # last external current measurement
    ext_r: float = None  # wire resistance, to calculate ext/batt voltage delta

    val_u: float = None  # voltage
    val_i: float = None  # current
    val_p: float = None  # momentary power
    val_t: list[float] = None  # other temperatures
    int_r: float = None  # internal resistance, whole battery

    # required modules
    cells: BaseCells = None
    balancer: BaseBalancer = None
    relay = None
    power = None  # reader for voltage and current

    sum_w: float = 0  # sum of u*i
    sum_c: float = 0  # sum of i

    _live_task = None
    live: int = None  # required msec between pings
    _main_task = None

    def __init__(self, cfg):
        self.cfg = cfg
        self.xmit_evt = Event()
        self.gen = 0  # generation, incremented every time a new value is read
        self._q = Broadcaster()

        super().__init__()

    async def run(self, cmd):
        """
        Main loop. Runs the cell and balancer main code.
        """
        self.t_last = ticks_ms()

        self.cmd = cmd
        self.sum_w = 0
        self.sum_c = 0
        self.n_w = 0
        self.live_flag = Event()

        async with TaskGroup() as tg:
            self.__tg = tg
            self._main_task = await tg.spawn(self._run)
            while True:
                await sleep(9999)

    async def update_power(
        self, u: float, i: float, p: float = None, w: float = None, c: float = None
    ):
        self.val_u = u
        self.val_i = i
        self.val_p = u * i if p is None else p
        if w is None or c is None:
            t = ticks_ms()
            td = ticks_diff(t, self.t_last)
            self.t_last = t

            if w is None:
                self.val_w += td * self.val_p
            else:
                self.val_w = w

            if c is None:
                self.val_c += td * self.val_i
            else:
                self.val_c = c
        await self.send_update("u_i")

    async def _live(self):
        while True:
            await timeout_ms(self.live, self._live_evt.wait)
            self._live_evt = Event()

    async def set_live(self, t):
        self.live = t
        if not t:
            if self._live_task is not None:
                self._live_task.cancel()
                self._live_task = None
                self._live_evt = None
        elif self._live_task is not None:
            self._live_evt.set()
        else:
            self._live_evt = Event()
            self._live_task = await self._tg.spawn(self._live)

    async def live_ping(self):
        if self._live_task is not None:
            self._live_evt.set()

    def stat(self, clear=False):
        """
        return current state + sums, optionally clear the sums
        """
        if self.relay is not None:
            rs = self.relay.state()
        else:
            rs = {}

        if self.live is not None:
            rs["l"] = self.live

        res = dict(
            u=self.last_u,
            i=self.last_i,
            s=dict(w=self.sum_w, c=self.sum_c, n=self.n_w),
            gen=self.gen,
        )
        if rs:
            res["r"] = rs

        if clear:
            self.sum_w = 0
            self.sum_c = 0
            self.n_w = 0
        return res

    async def set_relay_force(self, st):
        """
        manually change the relay's state
        """
        self.relay_force = st
        await self.relay.set(force=st)
        await self.send_rly_state("forced")

    async def live_state(self, live: bool):
        """
        is the system OK?
        """
        if self.live == live:
            return
        self.live = live
        if not live:
            await self.relay.set(False)
            await self.send_rly_state("Live Fail")

    def set_live(self):
        self.live_flag.set()

    async def live_task(self):
        while True:
            try:
                await wait_for_ms(self.cfg.poll.t.live, self.live_flag.wait)
            except TimeoutError:
                await self.live_state(False)
            else:
                self.live_flag = Event()
                await self.live_state(True)

    async def config_updated(self, cfg):
        """
        Kill it all off and restart.

        TODO: try to be somewhat less intrusive.
        """
        if self._main_task is None:
            self.cfg = cfg
            return
        self._main_task.cancel()
        await sleep_ms(100)
        self.cfg = cfg
        self._main_task = await self.__tg.spawn(self._run)

    async def send_work(self, flush: bool = False):
        if not self.cmd:
            return
        res = dict(
            w=self.sum_w,
            c=self.sum_c,
            n=self.n_w,
            f=flush,
        )
        if flush:
            self.sum_w = 0
            self.sum_c = 0
            self.n_w = 0
        await self.cmd.request.send_nr([self.cmd.name, "work"], **res)

    async def _run(self):
        async with TaskGroup() as tg:
            cfg = self.cfg
            try:
                self.cells = load_from_cfg(cfg.cells, bms=self)
            except AttributeError:
                breakpoint()
                raise
            self.balancer = load_from_cfg(cfg.balancer, cells=self.cells)
            self.relay = load_from_cfg(cfg.relay, bms=self, _raise=True)
            self.power = load_from_cfg(cfg.power, bms=self)

            if self.relay is not None:
                tg.start_soon(self.relay.run, self.cmd)
            if self.cells is not None:
                tg.start_soon(self.cells.run, self.cmd)
            if self.balancer is not None:
                tg.start_soon(self.balancer.run, self.cmd)
            if self.power is not None:
                tg.start_soon(self.power.run, self.cmd)

            await tg.spawn(self.live_task, _name="bms.live")
            await self._run_()

    async def _run_(self):
        xmit_n = 0
        self.live = (await self.relay.read())["s"]
        # we start off with the current relay state
        # so a soft reboot won't toggle the relay

        self.t = ticks_ms()

        while True:
            self.t = ticks_add(self.t, self.cfg.poll.t.voltage)

            if self.live:
                rs = self.relay.get_sync()

                if await self._check():
                    await self.relay.set(True)
                else:
                    await self.relay.set(False)

                if rs != self.relay.get_sync():
                    if rs:
                        await self.send_rly_state("Check OK")
                    else:
                        await self.send_rly_state("Check Fail")
                    xmit_n = 0

            xmit_n -= 1
            if xmit_n <= 0 or self.xmit_evt.is_set():
                if self.gen >= 99:
                    self.gen = 10
                else:
                    self.gen += 1
                self.xmit_evt.set()
                self.xmit_evt = Event()
                xmit_n = self.cfg.poll.n.voltage

            t = ticks_ms()
            td = ticks_diff(self.t, t)
            if td > 0:
                if self.n_w >= 10000:
                    await self.send_work()
                await sleep_ms(td)
            else:
                self.t = t

    async def send_rly_state(self, txt):
        self.xmit_evt.set()
        print("RELAY", (await self.relay.read()), txt, file=sys.stderr)


class BaseBMSCmd(BaseCmd):
    def __init__(self, parent: BaseCmd, name: str, cfg: attrdict, gcfg: attrdict):
        super().__init__(parent)
        self.name = name
        self.batt = None
        self.bms = load_from_cfg(cfg)
        if self.bms is None:
            raise ImportError(cfg)

    async def run(self):
        try:
            await self.bms.run(self)
        finally:
            self.bms = None

    async def config_updated(self, cfg):
        await super().config_updated(cfg)
        await self.bms.config_updated(cfg)

    async def cmd_rly(self, st=NotGiven):
        """
        Called manually, but also irreversibly when there's a "hard" cell over/undervoltage
        """
        rly = self.batt.relay
        if rly is None:
            raise RuntimeError("no relay")
        if st is NotGiven:
            return rly.state()
        await rly.set(force=st)

    async def cmd_info(self, gen=-1, r=False):
        if self.batt.gen == gen:
            await self.batt.xmit_evt.wait()
        return self.batt.stat(r)

    async def cmd_live(self, t=None):
        """
        Keepalive. Set t=x to require a call every t seconds.
        t=0 disables. No t is the ping.
        """
        if t is None:
            self.batt.ping()
        else:
            await self.batt.set_live(t)
