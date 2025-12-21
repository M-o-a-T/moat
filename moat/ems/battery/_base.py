"""
Basic BMS classes
"""

from __future__ import annotations

from moat.util import as_proxy, attrdict, val2pos
from moat.micro.alert import Alert
from moat.micro.cmd.array import ArrayCmd
from moat.micro.cmd.base import BaseCmd
from moat.micro.rtc import state as rtc_state
from moat.util.compat import (
    Event,
    TaskGroup,
    TimeoutError,  # noqa:A004
    log,
    sleep_ms,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.micro.cmd.alert import AlertHandler
    from moat.micro.cmd.tree.dir import SubDispatcher
    from moat.micro.part.relay import Relay


class BatteryAlert(Alert):
    """
    For a given battery there will at most be one open alert of each type.
    """


@as_proxy("bms_SH")
class HighSOC(BatteryAlert):
    "Charge exceeds limit"


@as_proxy("bms_SL")
class LowSOC(BatteryAlert):
    "Charge below limit"


@as_proxy("bms_UH")
class HighVoltage(BatteryAlert):
    "Total voltage exceeds limit"


@as_proxy("bms_UL")
class LowVoltage(BatteryAlert):
    "Total voltage below limit"


@as_proxy("bms_CH")
class HighCellVoltage(BatteryAlert):
    "Cell voltage exceeds limit"


@as_proxy("bms_CL")
class LowCellVoltage(BatteryAlert):
    "Cell voltage below limit"


@as_proxy("bms_CI")
class CellImbalance(BatteryAlert):
    "Excessive cell imbalance"


@as_proxy("bms_UD")
class VoltageDelta(BatteryAlert):
    "High diff between cell sum and total voltage"


@as_proxy("bms_IH")
class HighChargeCurrent(BatteryAlert):
    "Charge current exceeds limit"


@as_proxy("bms_IL")
class HighDischargeCurrent(BatteryAlert):
    "Discharge current exceeds limit"


@as_proxy("bms_TH")
class HighTemperature(BatteryAlert):
    "Temperature exceeds limit"


@as_proxy("bms_TL")
class LowTemperature(BatteryAlert):
    "Temperature below operational limit"


@as_proxy("bms_NBD")
class NoBatteryData(BatteryAlert):
    "no battery data seen"


@as_proxy("bms_NCD")
class NoCellData(BatteryAlert):
    "no cell data seen"


@as_proxy("bms_EL")
class EnergyLow(BatteryAlert):
    "total energy below zero"


@as_proxy("bms_EH")
class EnergyHigh(BatteryAlert):
    "total energy larger than Wmax"


def _s(r):
    # Helper to create a sequence
    return (x for x in r if x is not None)


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

    vchg: float | None = None
    vdis: float | None = None
    fchg: bool = False
    fdis: bool = False

    async def cmd_c(self):
        "read cell charge level [0…1]"
        raise NotImplementedError("no idea how")

    async def cmd_u(self):
        "read cell voltage"
        raise NotImplementedError("no idea how")

    async def cmd_t(self):
        "read cell temperature"
        raise NotImplementedError("no idea how")

    async def cmd_tb(self):
        "read cell balancer temperature"
        raise NotImplementedError("no idea how")

    doc_dis = dict(
        _d="bal discharge",
        v="float:threshold",
        f="bool:bypass balancer",
        _r=["float:current thresh", "bool:current bypass"],
    )

    async def cmd_dis(self, v: float | None = None, f: bool | None = None):
        """
        balance low: drain cell until below @v.

        If @f (force) is set, the cell will be skipped by the balancer;
        changing @v will be ignored if @f is `None`.

        Returns (voltage,force) tuple.
        """
        if f is not None:
            self.fdis = f
        if v is not None:
            if not self.fdis or f:
                self.vdis = v
                await self.set_dis()
        return (self.vdis, self.fdis)

    async def set_dis(self):
        """set discharging balancer"""
        raise NotImplementedError("no idea how")

    doc_chg = dict(
        _d="bal charge",
        v="float:threshold",
        f="bool:bypass balancer",
        _r=["float:current thresh", "bool:current bypass"],
    )

    async def cmd_chg(self, v: float | None = None, f: bool | None = None):
        """
        balance high: charge cell until above @v

        Obviously this only works with an active balancer.

        If @force is set, the cell will be skipped by the balancer.

        Returns (voltage,force) tuple.
        """
        if f is not None:
            self.fchg = f
        if v is not None:
            if not self.fchg or f:
                self.vchg = v
                await self.set_chg()
        return (self.vchg, self.fchg)

    async def set_chg(self):
        """set charging balancer"""
        raise NotImplementedError("no idea how")

    doc_lim = dict(
        _d="get limits",
        soc="float:current SoC,unknown=0.5",
        _r=["float:charge pct", "float:discharge pct"],
    )

    async def cmd_lim(self, soc: float = 0.5):
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

            tf = val2pos(lt["abs"]["max"], t, lt["ext"]["max"], clamp=True) * val2pos(
                lt["abs"]["min"],
                t,
                lt["ext"]["min"],
                clamp=True,
            )

        if u > lu["abs"]["max"]:
            raise HighCellVoltage(u, self.path)
        chg = tf * val2pos(lu["ext"]["max"], u, lu["std"]["max"], clamp=True)

        if u < lu["abs"]["min"]:
            raise LowCellVoltage(u, self.path)
        dis = tf * val2pos(lu["ext"]["min"], u, lu["std"]["min"], clamp=True)

        # TODO use an exponent != 1
        lc = self.cfg["lim"]["c"]
        if soc < lc["min"]:
            dis *= soc / lc["min"]
        if soc > lc["max"]:
            chg *= (1 - soc) / (1 - lc["max"])
        return (chg, dis)


class BalBaseCell(BaseCell):
    "A BaseCell with balancing state"

    in_balance: bool = False
    balance_pwm: float = None  # percentage of time the balancer is on
    balance_over_temp: bool = False
    balance_threshold: float = None
    balance_forced: bool = False

    doc_bal = dict(
        _d="get balancer state",
        _r=dict(
            b="bool:OK",
            f="bool:forced",
            ot="bool:overtemp",
            pwm="dict:pwm data",
            th="float:threshold",
        ),
    )

    async def cmd_bal(self):
        "Get Balancer state/data"
        res = dict(b=self.in_balance, f=self.balance_forced, ot=self.balance_over_temp)
        if self.balance_pwm is not None:
            res["pwm"] = self.balance_pwm
        if self.balance_threshold is not None:
            res["th"] = self.balance_threshold
        return res


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
          w: 1000000 # battery's total energy, in watt seconds
          lim:
            ud: 0.02 # relativ difference u/ud
          t:
            w: 500  # calculate cumulative energy every this-many-msec
            ud: 5000  # watch the difference between cell and cumulative voltage
          alarm: !P path.to.alarm.handler
          loss: 0.01 # average capacity loss when charging

    """

    w: attrdict = None
    w_max: float = None
    p: float = None
    al: SubDispatcher[AlertHandler] | None = None
    rly: SubDispatcher[Relay] | None = None
    n_warn_w = 0
    n_warn_ud = 0
    n_save = 98

    def __init__(self, cfg):
        super().__init__(cfg)
        self._reloaded = Event()
        self.clear_work()

    async def _setup(self):
        cfg = self.cfg
        self.al = self.root.sub_at(cfg["alarm"]) if "alarm" in cfg else None
        self.rly = self.root.sub_at(cfg["rly"]) if "relay" in cfg else None
        try:
            self.ud_max = cfg["lim"]["ud"]
        except KeyError:
            self.ud_max = 0.02
        try:
            self.t_w = cfg["t"]["w"]
        except KeyError:
            self.t_w = 500

        c = self.cfg["cfg"]["lim"]["u"]["ext"]
        n = self.cfg["n"]
        self.u_mid = (c["min"] + c["max"]) * n / 2

    async def setup(self):
        await super().setup()
        await self._setup()
        try:
            w = rtc_state[("state",) + self.path]
        except KeyError:
            pass
        else:
            self.work = attrdict(**w)

    doc_c = dict(_d="charge state", _r="float")

    async def cmd_c(self):
        """fetch charge state"""
        if self.w_max is None:
            return 0.5
        return self.w / self.w_max

    doc_u = dict(_d="voltage sum", _r="float")

    async def cmd_u(self):
        """fetch voltage sum"""
        r = await self.cmd_all("u")
        return sum(r)

    doc_t = dict(_d="min/max bat temp", _r=["float:min", "float:max"])

    async def cmd_t(self):
        """fetch temperature min/max"""
        r = await self.cmd_all("t")
        return min(_s(r), default=None), max(_s(r), default=None)

    doc_tb = dict(_d="min/max balancer temp", _r=["float:min", "float:max"])

    async def cmd_tb(self):
        """fetch balancer temperature min/max"""
        r = await self.cmd_all("tb")
        return min(_s(r), default=None), max(_s(r), default=None)

    doc_lim = dict(_d="chg/dischg limit factors", _r=["float:chg", "float:dischg"])

    async def cmd_lim(self):
        """return charge,discharge limit factors"""
        chg, dis = None, None
        try:
            for c, d in await self.cmd_all("lim"):
                if chg is None or chg > c:
                    chg = c
                if dis is None or dis > d:
                    dis = d
            return chg, dis

        except BatteryAlert:
            if self.rly is not None:
                await self.rly.w(v=False)
            raise

    async def reload(self):
        await super().reload()
        self._reloaded.set()
        self._reloaded = Event()

    async def monitor_ud(self):
        while True:
            try:
                await sleep_ms(self.cfg["t"]["ud"])
            except KeyError:
                await self._reloaded.wait()
                continue
            u = await self.cmd_u()
            ud = sum(await self.cmd_all("u"))
            if abs((u - ud) / ud) > self.ud_max:
                if self.al and not (self.n_warn_ud % 10):
                    await self.al.w(a=VoltageDelta, p=self.path, d=dict(u=u, ud=ud))
                self.n_warn_ud += 1
            elif self.n_warn_ud:
                self.n_warn_ud = 0
                await self.al.w(a=VoltageDelta, p=self.path)

    async def get_energy(self):
        """
        loop to calculate battery energy

        The base version sums up (u*i), i.e. watt seconds.
        """
        t1 = ticks_ms()
        i = await self.cmd_i()
        while True:
            await sleep_ms(self.t_w)
            u = await self.cmd_u()
            t2 = ticks_ms()
            self.p = p = i * u
            await self._add_w(p, ticks_diff(t2, t1) / 1000, u > self.u_mid)

            await sleep_ms(self.t_w)
            i = await self.cmd_i()
            t1 = ticks_ms()
            self.p = p = i * u
            await self._add_w(p, ticks_diff(t1, t2) / 1000, u > self.u_mid)

    doc_w = dict(_d="energy content", _r="float:current total", w="float:override")

    async def cmd_w(self, w: float | None = None) -> float:
        """get, or manually override, battery energy content"""
        wx = self.w
        if w is not None:
            self.clear_work(w)
        return wx

    def clear_work(self, w=None):
        if w is None:
            pass
        elif w < 0 or (self.w_max is not None and w > self.w_max):
            return False
        self.work = attrdict()
        self.work.sum = w or 0
        self.work.t = 0
        self.work.chg = 0
        self.work.dis = 0
        self.work.xchg = 0
        self.work.xdis = 0
        return True

    async def _add_w(self, w, t, hi):
        hi  # noqa:B018
        self.work.t += t
        w *= t

        if w > 0:
            self.work.chg += w
            w *= 1 - self.cfg.get("loss", 0)
        else:
            self.work.dis -= w
        self.work.sum += w

        # outside "standard" limits
        if self.work.sum < 0:
            self.work.xdis += -self.work.sum
            self.work.sum = 0
            if w < 0:
                if self.al and not (self.n_warn_w % 10):
                    await self.al.w(a=EnergyLow, p=self.path, d=dict(w=self.work.xdis, wd=w))
                self.n_warn_w += 1

        elif self.w_max is not None and self.work.sum > self.w_max:
            self.work.xchg += self.work.sum - self.w_max
            self.work.sum = self.w_max

            if w > 0:
                if self.al and not (self.n_warn_w % 10):
                    await self.al.w(a=EnergyHigh, p=self.path, d=dict(w=self.work.xchg, wd=w))
                self.n_warn_w += 1

        elif self.n_warn_w:
            self.n_warn_w = 0
            if self.w_max is None or self.work.sum < self.w_max / 2:
                await self.al.w(
                    a=EnergyLow if self.work.sum < self.w_max / 2 else EnergyHigh,
                    p=self.path,
                )

        self.n_save += 1
        if self.n_save > 99:
            self.n_save = 0
            rtc_state[("state",) + self.path] = self.work

    def get_work(self, clear: bool = False, poll: bool = False):
        poll  # noqa:B018
        res = self.work
        if clear:
            self.clear_work()
        return res

    async def start_tasks(self, tg):
        await tg.spawn(self.get_energy)
        await tg.spawn(self.monitor_ud)

    async def task(self):
        async with TaskGroup() as tg:
            await self.start_tasks(tg)
            await super().task()


class BaseBattery(BaseCells):
    """
    Skeleton for a balanced battery.
    """

    # superclass does sum of cell voltages
    #   async def cmd_u(self):
    #       """fetch battery voltage"""
    #       raise RuntimeError

    async def cmd_i(self):
        """fetch battery current"""
        raise RuntimeError

    doc_ud = dict(_d="delta current/total V", _r="float:sum(cell)-total")

    async def cmd_ud(self):
        """Get delta between cell voltage sum and battery voltage."""
        u1 = await self.cmd_u()
        u2 = sum(await self.all("u"))
        return u2 - u1


class BaseBalancer(BaseCmd):
    """
    Basic battery balancing.

    Config::
        bat: !P battery.to.balance
        t:
          chk: 1000  # time between checks when not balancing
          run: 500  # time between updates when balancing
        h:
          n: 3 # max parallel balancing
          d: 0.1  # min absolute voltage delta high vs. low
        u:
          max: 3.45  # no discharging below this point
          min: 3.05  # no charging above this point
    """

    # currently configured limits
    uh: float = None
    ul: float = None

    # configured limits, battery
    chg_max: float = None
    chg_min: float = None
    dis_max: float = None
    dis_min: float = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self._reloaded = Event()
        self._run = Event()

    async def reload(self):
        await super().reload()
        await self._setup()

    async def _setup(self):
        self.n = self.cfg.get("n", 9999)
        self.bat = self.root.sub_at(self.cfg["bat"]) if "bat" in self.cfg else None
        if self.bat is not None:
            # get battery limits
            c = await self.bat.cfg_(("cfg", "lim", "u", "ext"))
            self.dis_max = c["max"]
            self.chg_min = c["min"]
            c = await self.bat.cfg_(("cfg", "lim", "u", "std"))
            self.dis_min = c["max"]
            self.chg_max = c["min"]
            c = self.cfg.get("u", {})
            self.dis_min = max(self.dis_min, c.get("max", 0))
            self.chg_max = max(self.chg_max, c.get("min", 9999))
            if self.dis_min >= self.dis_max:
                raise RuntimeError("Cf dis")
            if self.chg_min >= self.chg_max:
                raise RuntimeError("Cf Chg")

            self._reloaded.set()
            self._reloaded = Event()

    async def setup(self):
        await super().setup()
        await self._setup()

    async def start_tasks(self, tg):
        await tg.spawn(self.run_bms)

    async def task(self):
        async with TaskGroup() as tg:
            await self.start_tasks(tg)
            await super().task()

    doc_u = dict(_d="V limits", h="float:max", l="float:min")

    async def cmd_u(self, h: float | None = None, l: float | None = None):  # noqa:E741
        "set desired voltage levels"
        if h is not None:
            self.uh = min(self.dis_max, max(self.dis_min, h))
        if l is not None:
            self.ul = min(self.chg_max, max(self.chg_min, l))
        self._run.set()

    async def run_bms(self):
        res = False
        while True:
            try:
                await wait_for_ms(self.cfg["t"]["run" if res else "chk"], self._run.wait)
            except KeyError:
                await self._reloaded.wait()
                continue
            except TimeoutError:
                pass
            if self.bat is None:
                await self._reloaded.wait()
                continue

            u = await self.bat.all("u")
            res = await self._run_h(u)
            # res = (await self._run_l(u)) || res

    async def _run_h(self, u):
        maxv = max(u)
        minv = min(u)

        # discharger states
        st = await self.bat.all("dis")

        if not self.uh or self.uh > maxv:
            for uv, f in st:
                if uv and not f:
                    await self.bat.all("dis", v=0)
                    break
            return
        try:
            d = self.cfg["h"]["d"]
        except KeyError:
            d = 0.05

        if maxv - minv < 2 * d or maxv < self.uh:
            # all OK. Don't do any (more) work.
            log("Bal- %.3f %.3f %.3f %.3f", minv, maxv, d, self.dis_min)
            await self.bat.all("dis", v=0)
            return

        thrv1 = self.uh
        minv = max(minv, self.dis_min)
        thrv2 = minv + 0.8 * (thrv1 - minv)  # small hysteresis
        cc = list(enumerate(u))
        cc.sort(key=lambda x: x[1], reverse=True)
        ret = False

        log("Bal %.3f %.3f %s %s", thrv1, thrv2, cc[0], cc[-1])

        want = 0
        cur = 0
        # Step 1, count what we currently have+need (and do some cleanup)
        for i, cv in cc:
            if st[i][1]:
                cur += 1
                continue

            if st[i][0] is not None:
                if st[i][0] < cv:
                    cur += 1
                    if st[i][0] < minv:
                        # don't balance below the minimum
                        log("Balance1 %s", cv)
                        await self.bat(i, "dis", v=cv)
                        # don't spam the system when the min level changes
                else:
                    # goal reached.
                    log("Unbalance1 %s", cv)
                    await self.bat(i, "dis", v=0)

            elif cv >= thrv1 + d:
                want += 1

        #       if cur:
        #           # update balancer power levels
        #           h, res = await self.send(RequestBalancePower())
        #           for c, r in zip(self.cells, res):
        #               r.to_cell(c)

        if cur or want:
            ret = True

        # Step 1, if there are too many active cells, reduce the load
        for i, cv in cc[::-1]:
            if want + cur <= self.n:
                # done
                break
            if st[i][1]:
                continue
            if st[i][0] > cv and cv < thrv2:
                log("Unbalance2 %s", cv)
                await self.bat(i, "dis", v=0)
                cur -= 1

        # Step 2, turn on balancing on cells that need it
        for i, cv in cc:
            if st[i][1]:
                continue
            if st[i][0]:
                continue
            if cur > self.n:
                break
            if cv >= thrv1 + d:
                log("Balance2 %d %s", i, cv)
                await self.bat(i, "dis", v=minv)
                cur += 1
                ret = True
                continue
            break

        return ret
