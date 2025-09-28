#
from __future__ import annotations

import anyio
import logging
from functools import cached_property

import asyncdbus.service as dbus
from asyncdbus.signature import Variant
from victron.dbus.utils import wrap_dbus_dict

from moat.util import attrdict, combine_dict
from moat.dbus import DbusInterface
from moat.util.compat import (
    Event,
    TaskGroup,
    sleep,
    sleep_ms,
)

from .. import ConfigError
from .cell import Cell
from .packet import *

logger = logging.getLogger(__name__)


def _t(x):
    if x is None:
        return -1000
    return x


class BatteryInterface(DbusInterface):
    def __init__(self, batt, dbus):
        self.batt = batt
        super().__init__(dbus, f"/bms/{self.batt.num or 0}", "bms")

    def done(self):
        del self.batt
        super().done()

    @dbus.method()
    def GetVoltages(self) -> "a{sd}":
        return self.batt.get_voltages()

    @dbus.method()
    async def Identify(self) -> b:
        h, _res = await self.batt.send(RequestIdentifyModule())
        return h.seen

    @dbus.method()
    def GetCellVoltages(self) -> ad:
        return [c.voltage for c in self.batt.cells]

    @dbus.method()
    def GetBalancing(self) -> a(dbdb):
        return [
            (
                c.balance_threshold or 0,
                c.in_balance,
                -1 if c.balance_pwm is None else c.balance_pwm,
                c.balance_forced,
            )
            for c in self.batt.cells
        ]

    @dbus.method()
    def GetConfig(self) -> "a{sv}a{sv}":
        return wrap_dbus_dict(self.batt.cfg), wrap_dbus_dict(self.batt.ccfg)

    @dbus.method()
    async def SetCapacity(self, cap: d, loss: d, top: b) -> b:
        """
        The battery capacity is @cap. The battery is currently
        charged (@top is true) or not (@top is False).
        """
        return await self.batt.set_capacity(cap, loss, top)

    @dbus.method()
    async def ForceRelay(self, on: b) -> b:
        self.batt.force_off = not on
        await self.batt.victron.update_dc(False)
        await self.batt.ctrl.req.send([self.batt.ctrl.name, "rly"], st=on)
        return True

    @dbus.method()
    def GetSoC(self) -> d:
        return self.batt.get_soc()

    @dbus.method()
    def SetSoC(self, soc: d) -> b:
        self.batt.set_soc(soc)
        return True

    @dbus.method()
    async def GetRelayState(self) -> bb:
        res = await self.batt.ctrl.req.send([self.batt.ctrl.name, "rly"])
        return bool(res[0]), bool(res[1])

    @dbus.method()
    async def ReleaseRelay(self) -> b:
        await self.batt.ctrl.req.send([self.batt.ctrl.name, "rly"], st=None)
        return True

    @dbus.method()
    def GetTemperatures(self) -> a(dd):
        return [(_t(c.load_temp), _t(c.batt_temp)) for c in self.batt.cells]

    @dbus.method()
    async def SetVoltage(self, data: d) -> b:
        # update the scale appropriately
        await self.batt.set_voltage(data)
        return True

    @dbus.method()
    async def SetExternalVoltage(self, data: d) -> b:
        # update correction factor
        await self.batt.set_ext_voltage(data)
        return True

    @dbus.method()
    def GetCurrent(self) -> d:
        return self.batt.current

    @dbus.method()
    async def SetCurrent(self, data: d) -> b:
        # update the scale appropriately
        await self.batt.set_current(data)
        return True

    @dbus.method()
    def GetCurrentOffset(self) -> d:
        return self.batt.cfg.i.offset

    @dbus.method()
    async def SetCurrentOffset(self, data: d) -> b:
        await self.batt.set_current_offset(data)
        return True

    @dbus.signal()
    async def CellVoltageChanged(self) -> a(db):
        """
        Send cell voltages and bypass flags
        """
        return [(c.voltage, c.in_balance) for c in self.batt.cells]

    @dbus.signal()
    async def VoltageChanged(self) -> ddbb:
        """
        Send pack voltage
        """
        batt = self.batt
        return (batt.voltage, batt.current, batt.chg_set or False, batt.dis_set or False)

    @dbus.signal()
    async def CellTemperatureChanged(self) -> a(vv):
        """
        Return cell temperatures (load, battery)

        False if there is no value
        """

        def F(x):
            return Variant("b", False) if x is None else Variant("d", x)

        return [(F(c.load_temp), F(c.batt_temp)) for c in self.batt.cells]

    @dbus.method()
    async def GetNCells(self) -> y:
        """
        Number of cells in this battery
        """
        return len(self.batt.cells)

    @dbus.method()
    async def GetName(self) -> s:
        """
        Number of cells in this battery
        """
        return self.batt.name

    @dbus.method()
    async def GetWork(self, poll: b, clear: b) -> "a{sd}":
        """
        Return work done by this battery
        """
        if poll:
            await self.batt.update_work()
        w = self.batt.get_work(clear)
        return w

    @dbus.method()
    async def SetWork(self, work: d) -> b:
        """
        Restore work done by this battery
        """
        return self.batt.clear_work(work=work)


class Battery:
    # global battery state, reported via MOAT callback
    voltage: float = None
    current: float = None
    power: float = None
    n_w: float = 0

    w_past: float = 0
    nw_past: float = 0

    msg_hi: bool = False
    msg_vhi: bool = False
    msg_lo: bool = False
    msg_vlo: bool = False
    msg_vsum: bool = False

    _charge = 0
    chg_set: bool = None
    dis_set: bool = None
    force_off: bool = False

    umax: float = None
    umin: float = None

    def __init__(self, ctrl, cfg, ccfg, gcfg, start, num):
        self.name = cfg.name if "name" in cfg else "battery1"
        self.num = num
        if num is None:
            num = 0
        self.ctrl = ctrl
        self.path = f"/bms/{num}"
        self.ready = 0

        self.cfg = cfg
        self.ccfg = ccfg
        self.gcfg = gcfg

        self.start = start
        self.end = start + self.cfg.n - 1

        self.ready_evt = Event()
        self.balance_evt = Event()

        self.cells = []
        for c in range(self.cfg.n):
            try:
                cf = cfg.cell.cells[c]
            except (AttributeError, IndexError):
                cf = attrdict()
            ccfg = combine_dict(cf, ccfg, cls=attrdict)
            cell = Cell(
                self,
                nr=self.start + c,
                path=f"/bms/{num}/{c}",
                cfg=ccfg,
                bcfg=self.cfg,
                gcfg=gcfg,
            )
            self.ctrl.add_cell(cell)
            self.cells.append(cell)
        self.clear_work()

    def __repr__(self):
        return f"‹Batt {self.path} u={0 if self.voltage is None else self.voltage:.3f} i={0 if self.current is None else self.current:.1f}›"

    @property
    def req(self):
        return self.ctrl.req

    @property
    def victron(self):
        return self.ctrl.victron

    @property
    def busname(self):
        return self.ctrl.busname

    @cached_property
    def cfg_path(self):
        return self.ctrl.cfgpath | "batteries" | self.batt.num

    async def run(self, evt):
        dbus = self.ctrl.dbus
        try:
            async with BatteryInterface(self, dbus) as intf:
                self._intf = intf

                await self._run(evt)
        finally:
            self._intf = None

    async def _run(self, evt):
        async with TaskGroup() as tg:
            logger.info("Talking to %s", self)
            h, res = await self.send(RequestIdentifyModule())
            if not h.seen:
                raise ConfigError(f"Battery {self.start}:{self.end}: ident found no cells")

            await self.send(RequestBalanceLevel(), broadcast=True)
            h, res = await self.send(RequestGetSettings())
            if len(res) != len(self.cells):
                raise ConfigError(
                    f"Battery {self.start}:{self.end}: config found {len(res)} modules, not {len(self.cells)}",
                )
            for c, r in zip(self.cells, res, strict=False):
                r.to_cell(c)

            h, res = await self.send(RequestReadPIDconfig())
            for c, r in zip(self.cells, res, strict=False):
                r.to_cell(c)

            for c in self.cells:
                await tg.spawn(c.run, _name="bms_c")

            await tg.spawn(self.task_keepalive, _name="bms_alive")
            await tg.spawn(self.task_voltage, _name="bms_v")
            await tg.spawn(self.task_cellvoltage, _name="bms_cv")
            await tg.spawn(self.task_celltemperature, _name="bms_ct")

            await self.ready_evt.wait()
            evt.set()
            logger.info("Ready: %s", self)

            while True:
                fast = await self.check_balancing()
                await sleep(5)
                if not fast:
                    with anyio.move_on_after(20):
                        await self.balance_evt.wait()
                        self.balance_evt = Event()

    async def config_updated(self):
        self.balance_evt.set()
        for c in self.cells:
            await c.config_updated()

    def trigger_balancing(self):
        self.balance_evt.set()

    # The cells have a certain spread of voltage levels. As the system voltage
    # increases, the allowed spread decreases because (a) when the system
    # charge level tops off, all cells must be at the same level; (b) when
    # a Lithium (esp. LiFePo4) cell gets closer to the maximum, a small
    # increase of charge will cause a large increase of voltage.
    #
    # Thus we calculate the allowed spread as a percentage of the range between
    # top voltage and the cell with lowest charge. Cells above that value get
    # balanced if they're above the minimum balance level.
    #
    # We balance the N top cells (to limit total heat release). However we
    # don't want to spam the system with balance requests if more than N cells
    # are close to each other, thus the additional secodn threshold.

    async def check_balancing(self):
        cfg = self.ccfg.balance
        minv = self.cell_min_voltage
        maxv = self.cell_max_voltage
        if maxv - minv < 2 * cfg.d or maxv < cfg.min:
            # all OK. Don't do any (more) work.
            logger.debug("Bal- %.3f %.3f %.3f %.3f", minv, maxv, cfg.d, cfg.min)
            for c in self.cells:
                if c.balance_forced:
                    continue
                if c.balance_threshold is not None:
                    logger.info("Unbalance0 %s", c)
                    await c.clear_balancing()
            return False

        thrv1 = minv + cfg.d + cfg.r * (self.ccfg.u.ext.max - minv)
        thrv1 = max(thrv1, cfg.min)
        minv = max(minv, cfg.min)
        thrv2 = minv + 0.8 * (thrv1 - minv)  # small hysteresis
        cc = self.cells[:]
        cc.sort(key=lambda x: x.voltage, reverse=True)
        ret = False

        logger.info("Bal %.3f %.3f %s %s", thrv1, thrv2, cc[0], cc[-1])

        want = 0
        cur = 0
        # Step 1, count what we currently have+need (and do some cleanup)
        for c in self.cells:
            if c.balance_forced:
                cur += 1
                continue

            if c.balance_threshold is not None:
                if c.in_balance:
                    cur += 1
                    if c.balance_threshold < minv:
                        # don't balance below the minimum
                        logger.info("Balance1 %s", c)
                        await c.set_balancing(minv + 2 * cfg.d)
                        # don't spam the system when the min level changes
                else:
                    # goal reached.
                    logger.info("Unbalance1 %s", c)
                    await c.clear_balancing()

            elif c.voltage >= thrv1 + cfg.d:
                want += 1

        if cur:
            # update balancer power levels
            h, res = await self.send(RequestBalancePower())
            for c, r in zip(self.cells, res, strict=False):
                r.to_cell(c)

        if cur or want:
            ret = True

        # Step 1, if there are too many active cells, reduce the load
        for c in cc[::-1]:
            if want + cur <= cfg.n:
                # done
                break
            if c.balance_forced:
                continue
            if c.in_balance and c.voltage < thrv2:
                logger.info("Unbalance2 %s", c)
                await c.clear_balancing()
                cur -= 1

        # Step 2, turn on balancing on cells that need it
        for c in cc:
            if c.balance_forced:
                continue
            if c.balance_threshold is not None:
                continue
            if cfg.n > 0 and cur > cfg.n:
                break
            if c.voltage >= thrv1 + cfg.d:
                logger.info("Balance2 %s", c)
                await c.set_balancing(minv)
                cur += 1
                ret = True
                continue
            break

        return ret

    async def task_keepalive(self):
        try:
            t = self.ctrl.cfg.poll.k / 2.1
        except AttributeError:
            return
        while True:
            await self.ctrl.req.send([self.ctrl.name, "live"])
            self.is_ready(0x01)

            await sleep_ms(t)

    def is_ready(self, val=None):
        if self.ready is None:
            return True
        if val is not None:
            self.ready |= val
        if self.ready == 0x0F:
            self.ready_evt.set()
            self.ready = None
            return True
        return False

    def clear_work(self, work=None):
        if work is None:
            pass
        elif work < 0 or work > self.cfg.cap.cur:
            return False
        self.work = attrdict()
        self.work.sum = work or 0
        self.work.t = 0
        self.work.chg = 0
        self.work.dis = 0
        self.work.over_chg = 0
        self.work.over_dis = 0
        self.work.cfg = self.cfg.cap.cur
        return True

    def add_work(self, w, n):
        cu = self.ccfg.u
        mi = self.cell_min_voltage

        if w > 0:
            self.work.chg += w
            w *= 1 - self.cfg.cap.loss
        else:
            self.work.dis -= w
        self.work.t += n
        self.work.sum += w

        # outside "standard" limits
        if mi < cu.lim.min:
            if self.work.sum > 0:
                self.work.over_dis -= self.work.sum
            self.work.sum = 0
        elif self.work.sum < 0:
            self.work.over_dis += -self.work.sum
            self.work.sum = 0

        if mi > cu.lim.max:
            if self.work.sum < self.cfg.cap.cur:
                self.work.over_chg -= self.cfg.cap.cur - self.work.sum
            self.work.sum = self.cfg.cap.cur
        elif self.work.sum > self.cfg.cap.cur:
            self.work.over_chg += self.work.sum - self.cfg.cap.cur
            self.work.sum = self.cfg.cap.cur

    def get_work(self, clear: bool = False, poll: bool = False):
        res = self.work
        if clear:
            self.clear_work()
        return res

    def get_voltages(self):
        return dict(
            min=self.min_voltage,
            max=self.max_voltage,
            bms=self.voltage,
            cells=self.sum_voltage,
            min_cell=self.cell_min_voltage,
            max_cell=self.cell_max_voltage,
            adj_cells=self.ccfg.u.corr,
        )

    async def update_work(self):
        res = await self.req.send([self.ctrl.name, "info"], r=True)
        data = res["w"]
        t = 1000 / self.ctrl.cfg.poll.t
        self.add_work(data["s"] / t, data["n"] / t)
        # watt seconds, seconds

    async def task_voltage(self):
        """
        Periodically check the battery voltages
        """
        gen = 0
        while True:
            res = await self.req.send([self.ctrl.name, "info"], gen=gen)
            gen = res.pop("gen", 0)
            self.update_global(**res)
            await self.check_limits(not self.is_ready())
            await self._intf.VoltageChanged()
            await self.victron.update_voltage()
            self.is_ready(0x08)

            await sleep(self.ctrl.cfg.t.voltage)

    async def task_cellvoltage(self):
        """
        Periodically check the cell voltages
        """
        while True:
            hdr, res = await self.send(RequestCellVoltage())
            chg = False
            for c, r in zip(self.cells, res, strict=False):
                chg = r.to_cell(c) or chg
            if chg:
                await self.check_limits(not self.is_ready())
                await self._intf.CellVoltageChanged()
            self.is_ready(0x02)

            await self.victron.update_cells()

            await sleep(self.ctrl.cfg.t.cellvoltage)

    def get_soc(self):
        cu = self.ccfg.u
        mi = self.cell_min_voltage

        # outside "standard" limits
        if mi < cu.lim.min:
            if self.work.sum > 0:
                self.work.over_dis -= self.work.sum
                self.work.sum = 0
            return 0.05 * max(0, (mi - cu.ext.min) / (cu.lim.min - cu.ext.min))
        if mi > cu.lim.max:
            if self.work.sum < self.cfg.cap.cur:
                self.work.over_chg -= self.cfg.cap.cur - self.work.sum
                self.work.sum = self.cfg.cap.cur
            return 1 - 0.05 * max(0, (cu.ext.max - mi) / (cu.ext.max - cu.lim.max))

        # OK, do the hopefully-somewhat-accurate charge level thing
        return 0.05 + 0.9 * min(1, max(0, self.work.sum / self.cfg.cap.cur))

    def get_cell_midvoltage(self):
        # returns (median, percentage_off)
        # The median is calculated by summing the voltages of the "low"
        # cells, rather than the midpoint voltage of the physical battery
        # (a) it's more expressive, (b) no guarantee that the cell order
        # reflects the physical battery layout
        v = [c.voltage for c in self.cells]
        v.sort()
        mp = len(v) // 2
        v_l = sum(v[:mp])
        v_h = sum(v[mp:])
        if len(v) % 2:
            v_l += v[mp] / 2
            v_h -= v[mp] / 2
        return v_l, (1 - v_l / v_h) * 100

    @property
    def cell_min_voltage(self):
        return min(c.voltage for c in self.cells)

    @property
    def cell_max_voltage(self):
        return max(c.voltage for c in self.cells)

    def get_pct_charge(self):
        cfg = self.ccfg

        v = self.cell_max_voltage
        try:
            return max(0, min(1, (cfg.u.ext.max - v) / (cfg.u.ext.max - cfg.u.lim.max)))
        except (ValueError, AttributeError):
            return 1

    def get_pct_discharge(self):
        cfg = self.ccfg

        v = self.cell_min_voltage
        try:
            return max(0, min(1, (v - cfg.u.ext.min) / (cfg.u.lim.min - cfg.u.ext.min)))
        except (ValueError, AttributeError):
            return 1

    #
    # We define min and max absolute voltage as the current cell voltage plus
    # the difference between the highest-charged cell and its max value.
    #
    # That being said maxvoltage will happily increase if warranted, but only decrease slowly.
    # Same in reverse for minvoltage.
    #
    @property
    def sum_voltage(self):
        try:
            return sum(c.voltage for c in self.cells)
        except TypeError:
            return self.voltage

    @property
    def max_voltage(self):
        u = 0
        umax = self.cell_max_voltage
        ud = self.ccfg.u.ext.max - umax

        if ud < 0:
            # owch
            return sum(min(c.cfg.u.ext.max, c.voltage) for c in self.cells)

        # ud is the voltage offset of the highest-voltage cell.
        # If this cell is close to 100% we risk overcharging when
        # setting the limit higher than the current voltage plus `ud`.
        # However if other cells are close to that (how close is controlled
        # by `cfg.u.range`, as a factor of `ud`) we'll assume that the other
        # cell voltages will rise also.

        # vlow is the voltage below which we don't consider a cell because
        # it's too far from the highest-voltage one.
        vrange = self.ccfg.u.range * ud
        vlow = umax - vrange
        # thus vrange == umax-vlow
        dplus = 0

        for c in self.cells:
            if c.voltage > vlow:
                # thus this scale factor is 1 for the highest-voltage cell
                # and between 0 and 1 otherwise
                dplus += ud * (c.voltage - vlow) / vrange

        u = self.sum_voltage + dplus

        # If we found a higher maximum charge voltage we'll use that.
        # Otherwise the old maximum will decay slowly. if the battery
        # becomes less-than-perfectly-balanced after a discharge
        # we don't use the old value.
        if self.umax is None or self.umax < u:
            self.umax = u
        else:
            self.umax += 0.001 * (u - self.umax)
        return self.umax

    @property
    def min_voltage(self):
        # mirror of `max_voltage`
        u = 0
        umin = self.cell_min_voltage
        ud = umin - self.ccfg.u.ext.min

        if ud < 0:
            # owch
            return sum(max(c.cfg.u.ext.min, c.voltage) for c in self.cells)

        vrange = self.ccfg.u.range * ud
        vhigh = umin + vrange
        # thus vrange == vhigh-umin
        dplus = 0

        for c in self.cells:
            if c.voltage < vhigh:
                # thus this scale factor is 1 for the highest-voltage cell
                # and between 0 and 1 otherwise
                dplus += ud * (vhigh - c.voltage) / vrange

        u = self.sum_voltage - dplus

        # If we found a new minimum charge voltage we'll use that.
        # Otherwise the old minimum will decay (very) slowly, so if the battery
        # becomes less-than-perfectly-balanced after a discharge
        # we don't use the old value.
        if self.umin is None or self.umin > u:
            self.umin = u
        else:
            self.umin += 0.001 * (u - self.umin)
        return self.umin

    async def check_limits(self, init=False):
        """
        Verify that the battery voltages are within spec.
        """
        chg_ok = True
        dis_ok = True
        off = False

        try:
            self.voltage + 0
            umax = (self.max_voltage + self.cfg.u.max) / 2
            umin = (self.min_voltage + self.cfg.u.min) / 2
        except TypeError:
            pass
        else:
            try:
                vsum = sum(c.voltage for c in self.cells)
            except TypeError:
                pass
            else:
                if not self.msg_vsum and abs(vsum - self.voltage) > vsum * 0.02:
                    logger.warning(
                        "Voltage doesn't match: reported %.2f, sum %.2f",
                        self.voltage,
                        vsum,
                    )
                    self.msg_vsum = True
                elif self.msg_vsum and abs(vsum - self.voltage) < vsum * 0.015:
                    logger.warning(
                        "Voltage matches again: reported %.2f, sum %.2f",
                        self.voltage,
                        vsum,
                    )
                    self.msg_vsum = False

            if self.voltage >= umax:
                if not self.msg_hi:
                    logger.warning("Voltage %.2f high, no charging", self.voltage)
                    self.msg_hi = True
                chg_ok = False
            elif self.msg_hi and self.voltage < umax - 0.05:
                logger.warning("Voltage %.2f no longer high, charging OK", self.voltage)
                self.msg_hi = False

            if self.voltage >= self.cfg.u.max:
                off = True
                if not self.msg_vhi:
                    logger.error("Overvoltage %.2f, turned off", self.voltage)
                    self.msg_vhi = True
            elif self.msg_vhi:
                logger.error("Overvoltage %.2f fixed", self.voltage)
                self.msg_vhi = False

            if self.voltage <= umin:
                if not self.msg_lo:
                    breakpoint()
                    self.min_voltage  # step thru
                    logger.warning("Voltage %.2f low, no discharging", self.voltage)
                    self.msg_lo = True
                dis_ok = False
            elif self.msg_lo and self.voltage > umin + 0.05:
                logger.warning("Voltage %.2f no longer low, discharging OK", self.voltage)
                self.msg_lo = False

            if self.voltage <= self.cfg.u.min:
                off = True
                if not self.msg_vlo:
                    logger.error("Undervoltage %.2f, turned off", self.voltage)
                    self.msg_vlo = True
            elif self.msg_vlo:
                logger.error("Undervoltage %.2f fixed", self.voltage)
                self.msg_vlo = False

        if self.current is not None:
            pass  # XXX TODO check current limits here also

        for c in self.cells:
            ucmax = (c.cfg.u.max + c.cfg.u.ext.max) / 2
            ucmax2 = (c.cfg.u.max + 2 * c.cfg.u.ext.max) / 3
            ucmin = (c.cfg.u.min + c.cfg.u.ext.min) / 2
            ucmin2 = (c.cfg.u.min + 2 * c.cfg.u.ext.min) / 3

            if c.voltage is not None:
                if c.voltage >= ucmax:
                    if not c.msg_hi:
                        logger.warning("%s voltage high, no charging", c)
                        c.msg_hi = True
                elif c.msg_hi and c.voltage < ucmax2:
                    logger.warning("%s voltage no longer high", c)
                    c.msg_hi = False
                if c.msg_hi:
                    chg_ok = False

                if c.voltage >= c.cfg.u.max:
                    if not c.msg_vhi:
                        logger.error("%s overvoltage, turned off", c)
                        c.msg_vhi = True
                    off = True
                elif c.msg_vhi:
                    logger.error("%s overvoltage fixed", c)
                    c.msg_vhi = False

                if c.voltage <= ucmin:
                    if not c.msg_lo:
                        logger.warning("%s voltage low, no discharging", c)
                        c.msg_lo = True
                elif c.msg_lo and c.voltage > ucmin2:
                    logger.warning("%s voltage no longer low", c)
                    c.msg_lo = False
                if c.msg_lo:
                    dis_ok = False

                if c.voltage <= c.cfg.u.min:
                    off = True
                    if not c.msg_vlo:
                        logger.error("%s undervoltage, turned off", c)
                        c.msg_vlo = True
                elif c.msg_vlo:
                    logger.error("%s undervoltage fixed", c)
                    c.msg_vlo = False

        if off:
            if self.is_ready():
                await self.ctrl.req.send([self.ctrl.name, "rly"], st=False)
            else:
                logger.fatal("DANGER not ready, relay not turning off DANGER")

        # send limits to BMS in mplex
        self.chg_set = chg_ok
        self.dis_set = dis_ok
        try:
            await self.victron.update_dc(init)
        except (TypeError, ValueError):
            if self.is_ready():
                raise

    async def task_celltemperature(self):
        """
        Periodically check the cell temperatures
        """
        while True:
            hdr, res = await self.send(RequestCellTemperature())
            chg = False
            for c, r in zip(self.cells, res, strict=False):
                chg = r.to_cell(c) or chg
            if chg:
                await self._intf.CellTemperatureChanged()
                await self.victron.update_temperature()
            self.is_ready(0x04)

            await sleep(self.ctrl.cfg.t.celltemperature)

    async def send(self, pkt, start=None, end=None, **kw):
        """
        Send a message to "my" cells.
        """
        if start is None:
            start = self.start
        if end is None:
            end = self.end
        return await self.ctrl.send(pkt, start=start, end=end, **kw)

    def update_global(self, u=None, i=None, w=None, r=None, **kw):
        if r is not None:
            self.force_off = not r["s"]

        if u is not None:
            self.voltage = u

        if i is not None:
            self.current = i

        if w is not None:
            s = w["s"]
            n = w["n"]
            if n < self.n_w:
                self.w_past += self.power
                self.nw_past += self.n_w
            self.power = s
            self.n_w = n

    async def set_voltage(self, val):
        # TODO move this to a config update handler
        adj = (val - self.cfg.u.offset) / (self.voltage - self.cfg.u.offset)
        self.cfg.u.scale *= adj
        await self._send_cfg("u", scale=self.cfg.u.scale)
        self.voltage = val
        return True

    async def set_ext_voltage(self, val):
        # TODO move this to a config update handler
        adj = val / self.sum_voltage
        await self._send_cfg("u", corr=adj)
        self.voltage = val
        return True

    async def set_current(self, val):
        # TODO move this to a config update handler
        adj = (val - self.cfg.i.offset) / (self.current - self.cfg.i.offset)
        self.cfg.i.scale *= adj
        await self._send_cfg("i", scale=self.cfg.i.scale)
        self.current = val

    async def set_current_offset(self, val):
        # TODO move this to a config update handler
        self.cfg.i.offset = val
        await self._send_cfg("i", offset=self.cfg.i.offset)

    async def _send_cfg(self, *a, **kv):
        if self.num is None:
            await self.ctrl.cmd.send(
                ["sys", "cfg"],
                cfg=attrdict()._update((self.ctrl.name, "batt", *a), kv),
            )
        else:
            await self.ctrl.cmd.send(
                ["sys", "cfg"],
                cfg=attrdict()._update((self.ctrl.name, "batt", self.num, *a), kv),
            )
        return True

    async def set_capacity(self, cap, loss, top):
        if loss < 0 or loss >= 1:
            return False
        await self._send_cfg("cap", cur=cap, loss=loss)
        if top:
            self.work.sum = cap
        else:
            self.work.sum = 0
        return True
