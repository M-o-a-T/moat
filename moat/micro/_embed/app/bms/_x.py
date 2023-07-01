import sys

import time
from moat.util import NotGiven, Alert, AlertMixin, Broadcaster

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
)

from anyio import create_memory_object_stream as _cmos
from anyio import Event


class BatteryAlert(Alert):
    """
    For a given battery there will at most be one open alert of each type.
    """


class HighSOC(BatteryAlert):
    "Charge exceeds limit"


class LowSOC(BatteryAlert):
    "Charge below limit"


class HighVoltage(BatteryAlert):
    "Total voltage exceeds limit"


class LowVoltage(BatteryAlert):
    "Total voltage below limit"


class HighCellVoltage(BatteryAlert):
    "Cell voltage exceeds limit"


class LowCellVoltage(BatteryAlert):
    "Cell voltage below limit"


class CellImbalance(BatteryAlert):
    "Excessive cell imbalance"


class HighChargeCurrent(BatteryAlert):
    "Charge current exceeds limit"


class HighDischargeCurrent(BatteryAlert):
    "Discharge current exceeds limit"


class HighTemperature(BatteryAlert):
    "Temperature exceeds limit"


class LowTemperature(BatteryAlert):
    "Temperature below operational limit"


class NoBatteryData(BatteryAlert):
    "no battery data seen"


class NoCellData(BatteryAlert):
    "no cell data seen"


class VoltageDelta(BatteryyAlert):
    "Battery and sum-of-cell voltages don't match"


class BaseCells:
    """
    Skeleton of a cell array.
    """

    def __init__(self, cfg):
        self.cfg = cfg

    async def read_u(self):
        """fetch all cells' voltages"""
        raise NotImplementedError("no idea how")

    async def read_t(self):
        """fetch all cells' temperatures"""
        raise NotImplementedError("no idea how")

    async def run(self):
        pass


class BaseBalancer:
    """
    Skeleton of a balancing controller
    """

    def __init__(self, cells: BaseCells, cfg: attrdict):
        self.cells = cells
        self.cfg = cfg

    async def run(self):
        pass  # TODO


class BaseBMS(AlertMixin):
    """
    This is the skeleton of a battery monitor.
    """

    cmd = None

    ext_u: float = None  # external voltage
    ext_i: float = None  # external current
    ext_r: float = None  # wire resistance, to calculate ext/batt voltage delta

    cell_u: list[float] = None  # cell voltages
    cell_t: list[float] = None  # cell temperatures

    cell_ms: int = None  # last cell update

    bat_u: float = None  # voltage
    bat_i: float = None  # current
    bat_p: float = None  # momentary power
    bat_t: list[float] = None  # other temperatures
    bat_r: float = None  # internal resistance, whole battery

    bat_ms: int = None  # last battery update, msec

    sum_w: float = 0  # sum of u*i
    sum_c: float = 0  # sum of i
    sum_ms: int = 0  # timespan for sum_X

    def __init__(self, cfg):
        self.cfg = cfg
        self.xmit_evt = Event()
        self.gen = 0  # generation, incremented every time a new value is read
        self._q = Broadcaster()
        self._qw, self._qr = _cmos(10)
        super().__init__()

    async def _agg_bat(self):
        # aggregate U and I values
        u = i = t = None
        q = iter(self._q)

        # setup
        async for val in q:
            if "bat_u" in val:
                u = val.bat_u
            if "bat_i" in val:
                i = val.bat_i
            if i is None or u is None:
                continue
            t = ticks_ms()
            break

        async for val in q:
            work = False
            if "bat_u" in val:
                u = val.bat_u
                work = True
            if "bat_i" in val:
                i = val.bat_i
                work = True
            if not work:
                continue
            td = ticks_delta(val.t, t)
            self.sum_w += td * u * i
            self.sum_c += td * i
            t = val.t
            continue

    async def _read_bat_u(self):
        rdr = load_from_cfg(self.cfg.u)
        while True:
            for val in every_ms(cfg.t, rdr.read):
                self._q(attrdict(bat_u=val))

    async def _read_bat_i(self):
        rdr = load_from_cfg(self.cfg.i)
        while True:
            for val in every_ms(cfg.t, rdr.read):
                self._q(attrdict(bat_i=val))

    async def _read_bat_t(self):
        rdr = load_from_cfg(self.cfg.t)
        while True:
            for val in every_ms(cfg.t, rdr.read):
                self._q(attrdict(bat_i=val))

    async def run(self):
        """
        Main loop.
        """
        t = time.monotonic()
        async with TaskGroup() as tg:
            tg.start_soon(self._read_cell_u)
            tg.start_soon(self._read_cell_t)
            tg.start_soon(self._read_bat_u)
            tg.start_soon(self._read_bat_i)
            tg.start_soon(self._read_bat_t)
            tg.start_soon(self._agg_bat)

    async def _check(self) -> None:
        """
        Verify basic battery parameters

        It polls / sums values and sends alerts, and may trip the relay.
        """

        c = self.cfg
        cc = c["batt"]
        d = c["poll"]["d"]

        u = await self.read_voltage()
        i = await self.read_current()
        self.val_u = u
        self.val_i = i

        self.sum_w += u * i
        self.sum_c += i
        self.n_w += 1

        if u < cc.u.min:
            self.alert_(LowVoltage, u)
        else:
            self.alert_(LowVoltage)
        if u > cc.u.max:
            self.alert_(HighVoltage, u)
        else:
            self.alert_(HighVoltage)
        if i < cc.i.min:
            self.alert_(HighDischargeCurrent, i)
        else:
            self.alert_(HighDischargeCurrent)
        if i > cc.i.max:
            self.alert_(HighChargeCurrent, i)
        else:
            self.alert_(HighChargeCurrent)

    def stat(self, clear=False):
        """
        return current state + sums, optionally clear the sums
        """
        res = dict(
            u=self.val_u,
            i=self.val_i,
            s=dict(w=self.sum_w, c=self.sum_c, n=self.n_w),
            r=dict(s=self.relay.value(), f=self.relay_force, l=self.live),
            gen=self.gen,
        )
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
        if st is not None:
            self.relay.value(st)
            await self.send_rly_state("forced")
        else:
            await self.send_rly_state("auto")
            if not self.relay.value():
                self.sw_ok = False
                self.t_sw = ticks_add(self.t, self.cfg["relay"]["t"])
                print("DLY", self.cfg["relay"]["t"], file=sys.stderr)

    def live_state(self, live: bool):
        """
        is the system OK?
        """
        if self.live == live:
            return
        self.live = live
        if not live:
            self.relay.off()
            await self.send_rly_state("Live Fail")

    def set_live(self):
        self.live_flag.set()

    async def live_task(self):
        while True:
            try:
                await wait_for_ms(self.cfg.poll.k, self.live_flag.wait)
            except TimeoutError:
                self.live_state(False)
            else:
                self.live_flag = Event()
                self.live_state(True)

    async def config_updated(self, cfg):
        await self.send_work(flush=True)

        self.cfg = cfg
        self._setup()

    async def send_work(self, flush: bool = False):
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
        await self.request.send_nr([self.name, "work"], **res)

    def _set_scales(self):
        c = self.cfg.batt
        self.adc_u_scale = c.u.scale
        self.adc_u_offset = c.u.offset
        self.adc_i_scale = c.i.scale
        self.adc_i_offset = c.i.offset

    async def run(self):
        c = self.cfg.batt
        self.adc_u = M.ADC(M.Pin(c["u"]["pin"]))
        self.adc_i = M.ADC(M.Pin(c["i"]["pin"]))
        self.adc_ir = M.ADC(M.Pin(c["i"]["ref"]))
        self.relay = M.Pin(self.cfg["relay"]["pin"], M.Pin.OUT)
        self.sum_w = 0
        self.sum_c = 0
        self.n_w = 0
        self.relay_force = None
        self.live = self.relay.value()
        self.live_flag = Event()
        # we start off with the current relay state
        # so a soft reboot won't toggle the relay

        self._set_scales()

        def sa(a, n=10):
            s = 0
            for _ in range(n):
                s += a.read_u16()
            return s / n

        self.val_u = sa(self.adc_u) * self.adc_u_scale + self.adc_u_offset
        self.val_i = (sa(self.adc_i) - sa(self.adc_ir)) * self.adc_i_scale + self.adc_i_offset

        self.sw_ok = False

        self.t = ticks_ms()
        self.t_sw = ticks_add(ticks_ms(), self.cfg["relay"]["t1"])

        async with TaskGroup() as tg:
            await tg.spawn(self.live_task, _name="bms.live")
            await self._run()

    async def _run(self):
        xmit_n = 0
        while True:
            self.t = ticks_add(self.t, self.cfg["poll"]["t"])

            if not self.sw_ok:
                if ticks_diff(self.t, self.t_sw) > 0:
                    self.sw_ok = True
                    xmit_n = 0

            if await self._check():
                if (
                    self.sw_ok
                    and self.live
                    and self.relay_force is None
                    and not self.relay.value()
                ):
                    self.relay.on()
                    await self.send_rly_state("Check OK")
                    xmit_n = 0

            elif self.live and self.relay_force is None and self.relay.value():
                self.relay.off()
                await self.send_rly_state("Check Fail")
                self.t_sw = ticks_add(self.t, self.cfg["relay"]["t"])
                self.sw_ok = False
                xmit_n = 0

            xmit_n -= 1
            if xmit_n <= 0 or self.xmit_evt.is_set:
                if self.gen >= 99:
                    self.gen = 10
                else:
                    self.gen += 1
                self.xmit_evt.set()
                self.xmit_evt = Event()
                xmit_n = self.cfg["poll"]["n"]

            t = ticks_ms()
            td = ticks_diff(self.t, t)
            if td > 0:
                if self.n_w >= 1000:
                    await self.send_work()
                await sleep_ms(td)
            else:
                self.t = t

    async def send_rly_state(self, txt):
        self.xmit_evt.set()
        print("RELAY", self.relay.value(), txt, file=sys.stderr)


class BMSCmd(BaseCmd):
    def __init__(self, parent, name, cfg):
        super().__init__(parent, name)

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
        if st is NotGiven:
            return self.bms.relay.value(), self.bms.relay_force
        await self.bms.set_relay_force(st)

    async def cmd_info(self, gen=-1, r=False):
        if self.bms.gen == gen:
            await self.bms.xmit_evt.wait()
        return self.bms.stat(r)

    def cmd_live(self):
        self.bms.set_live()
