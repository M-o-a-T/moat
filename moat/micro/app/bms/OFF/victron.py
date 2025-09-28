from __future__ import annotations

import anyio
import contextlib
import logging

from victron.dbus import Dbus

from moat.util import Queue, attrdict
from moat.util.compat import (
    Event,
)

logger = logging.getLogger(__name__)

# cfg:
#   batt:
# u:
#   pin: PIN  # measure U
#   min: VAL
#   max: VAL
# i:
#   pin: PIN  # measure I
#   ref: PIN  # I reference, subtract from measurement
#   min: VAL
#   max: VAL
# poll:
#   t: MSEC
#   d: FACTOR # decay, for averaging, 1000/th
# rel: PIN  # relay
#


class BatteryState:
    cell_okchg = None
    cell_okdis = None
    data = None
    u = None
    i = None
    ctrl = None

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.q = Queue(2)
        self.started = Event()
        self.updated = Event()

    async def config_updated(self):
        pass

    async def update_dc(self, init=True):
        b = self.ctrl.batt[0]
        u_min = b.min_voltage * b.ccfg.u.corr
        u_max = b.max_voltage * b.ccfg.u.corr
        i_min = b.cfg.i.ext.min
        i_max = b.cfg.i.ext.max
        c_min = b.get_pct_discharge()
        c_max = b.get_pct_charge()
        fudge = 0.1 if init else 0

        for b in self.ctrl.batt[1:]:
            c = b.cfg
            u_min = max(u_min, b.min_voltage * b.ccfg.u.corr)
            u_max = min(u_max, b.max_voltage * b.ccfg.u.corr)
            i_min += c.i.ext.min
            i_max += c.i.ext.max
            c_min = min(c_min, b.get_pct_discharge())
            # c_max = min(c_max, b.get_pct_charge())
            # All of this assumes that the batteries are "mostly" identical,
            # which might be wrong.

        # update charge and discharge flags
        chg_ok = all(b.chg_set for b in self.ctrl.batt)
        dis_ok = all(b.dis_set for b in self.ctrl.batt)
        force_off = any(b.force_off for b in self.ctrl.batt)
        if force_off:
            chg_ok = False
            dis_ok = False

        async with self._srv as l:
            await l.set(self.bus.vlo, float(u_min + fudge))
            await l.set(self.bus.vhi, float(u_max + fudge))
            await l.set(self.bus.idis, -float(i_min) * c_min + fudge if dis_ok else 0)
            await l.set(self.bus.ich, float(i_max) * c_max - fudge if chg_ok else 0)

            await l.set(self.bus.okchg, int(chg_ok))
            await l.set(self.bus.okdis, int(dis_ok))

    async def update_cells(self):
        ch = None
        cl = None
        nbc = 0
        nbd = 0

        for c in self.ctrl.cells:
            if c.voltage is None:
                continue
            if cl is None or cl.voltage > c.voltage:
                cl = c
            if ch is None or ch.voltage < c.voltage:
                ch = c
            if c.voltage < c.cfg.u.ext.min:
                nbd += 100
            if c.voltage > c.cfg.u.ext.max:
                nbc += 100

        soc = 0
        for b in self.ctrl.batt:
            ub = b.sum_voltage
            if ub < b.cfg.u.ext.min:
                nbd += 1
            if ub > b.cfg.u.ext.max:
                nbc += 1
            soc += b.get_soc()

        bal = any(c.in_balance for c in self.ctrl.cells)
        async with self.srv as l:
            mv, mvd = self.ctrl.batt[0].get_cell_midvoltage()
            await l.set(self.bus.mv0, mv)
            await l.set(self.bus.mvd0, mvd)

            await l.set(self.bus.mincv, cl.voltage)
            await l.set(self.bus.mincvi, str(cl.nr))
            await l.set(self.bus.maxcv, ch.voltage)
            await l.set(self.bus.maxcvi, str(ch.nr))

            await l.set(self.bus.nbc, nbc)
            await l.set(self.bus.nbd, nbd)

            await l.set(self.bus.bal, int(bal))
            await l.set(self.bus.soc, soc / len(self.ctrl.batt) * 100)

    async def update_boot(self):
        cfg = self.ctrl.batt[0].cfg

        async with self.srv as l:
            with contextlib.suppress(AttributeError):
                await l.set(self.bus.cap, cfg.cap.ah)
            with contextlib.suppress(AttributeError):
                await l.set(self.bus.capi, cfg.cap.cur / 3600 / cfg.n / cfg.u.nom)
            await l.set(self.bus.ncell, len(self.ctrl.cells) // len(self.ctrl.batt))

        await self.update_cells()
        await self.update_dc(True)
        await self.update_voltage()
        await self.update_temperature()

    async def update_voltage(self):
        ok = False
        try:
            u = sum(b.sum_voltage for b in self.ctrl.batt) / len(self.ctrl.batt)
            i = sum(b.current for b in self.ctrl.batt)
            ok = True
        except ValueError:
            u = i = None

        async with self.srv as l:
            await l.set(self.bus.sta, 9 if ok else 10)
            await l.set(self.bus.err, 0 if ok else 12)
            await l.set(self.bus.v0, u)
            await l.set(self.bus.c0, i)
            await l.set(self.bus.p0, u * i if u is not None else None)

    async def update_temperature(self):
        ch = None
        cl = None
        t = 0
        tn = 0
        for c in self.ctrl.cells:
            if c.batt_temp is None:
                continue
            if cl is None or cl.batt_temp > c.batt_temp:
                cl = c
            if ch is None or ch.batt_temp < c.batt_temp:
                ch = c
            t += c.batt_temp
            tn += 1

        if tn:
            async with self.srv as l:
                await l.set(self.bus.t0, t / tn)
                await l.set(self.bus.minct, cl.batt_temp)
                await l.set(self.bus.mincti, str(cl.nr))
                await l.set(self.bus.maxct, ch.batt_temp)
                await l.set(self.bus.maxcti, str(ch.nr))

    @property
    def name(self):
        return self.ctrl.name

    @property
    def srv(self):
        return self._srv

    async def run(self, bus, evt=None):
        name = "com.victronenergy.battery." + self.name
        async with Dbus(bus) as _bus, _bus.service(name) as srv:
            logger.debug("Setting up")
            self.bus = attrdict()
            self._srv = srv

            await srv.add_mandatory_paths(
                processname=__file__,
                processversion="0.1",
                connection="MoaT " + self.ctrl.gcfg.port.dev,
                deviceinstance="1",
                serial="123456",
                productid=123210,
                productname="MoaT BMS",
                firmwareversion="0.1",
                hardwareversion=None,
                connected=1,
            )

            self.bus.vlo = await srv.add_path(
                "/Info/BatteryLowVoltage",
                None,
                gettextcallback=lambda p, v: f"{v:0.2f} V",
            )
            self.bus.vhi = await srv.add_path(
                "/Info/MaxChargeVoltage",
                None,
                gettextcallback=lambda p, v: f"{v:0.2f} V",
            )
            self.bus.ich = await srv.add_path(
                "/Info/MaxChargeCurrent",
                None,
                gettextcallback=lambda p, v: f"{v:0.2f} A",
            )
            self.bus.idis = await srv.add_path(
                "/Info/MaxDischargeCurrent",
                None,
                gettextcallback=lambda p, v: f"{v:0.2f} A",
            )

            self.bus.sta = await srv.add_path("/State", 1)
            self.bus.err = await srv.add_path("/Error", 0)
            self.bus.ncell = await srv.add_path("/System/NrOfCellsPerBattery", None)
            self.bus.non = await srv.add_path("/System/NrOfModulesOnline", 1)
            self.bus.noff = await srv.add_path("/System/NrOfModulesOffline", 0)
            self.bus.nbc = await srv.add_path("/System/NrOfModulesBlockingCharge", None)
            self.bus.nbd = await srv.add_path("/System/NrOfModulesBlockingDischarge", None)
            self.bus.cap = await srv.add_path("/Capacity", 4.0)
            self.bus.capi = await srv.add_path("/InstalledCapacity", 5.0)
            self.bus.cons = await srv.add_path("/ConsumedAmphours", 12.3)

            self.bus.soc = await srv.add_path("/Soc", 30)
            self.bus.soh = await srv.add_path("/Soh", 90)
            self.bus.v0 = await srv.add_path(
                "/Dc/0/Voltage",
                None,
                gettextcallback=lambda p, v: f"{v:2.2f}V",
            )
            self.bus.c0 = await srv.add_path(
                "/Dc/0/Current",
                None,
                gettextcallback=lambda p, v: f"{v:2.2f}A",
            )
            self.bus.p0 = await srv.add_path(
                "/Dc/0/Power",
                None,
                gettextcallback=lambda p, v: f"{v:0.0f}W",
            )
            self.bus.t0 = await srv.add_path("/Dc/0/Temperature", 21.0)
            self.bus.mv0 = await srv.add_path(
                "/Dc/0/MidVoltage",
                None,
                gettextcallback=lambda p, v: f"{v:0.2f}V",
            )
            self.bus.mvd0 = await srv.add_path(
                "/Dc/0/MidVoltageDeviation",
                None,
                gettextcallback=lambda p, v: f"{v:0.1f}%",
            )

            # battery extras
            self.bus.minct = await srv.add_path("/System/MinCellTemperature", None)
            self.bus.maxct = await srv.add_path("/System/MaxCellTemperature", None)
            self.bus.maxcv = await srv.add_path(
                "/System/MaxCellVoltage",
                None,
                gettextcallback=lambda p, v: f"{v:0.3f}V",
            )
            self.bus.maxcvi = await srv.add_path("/System/MaxVoltageCellId", None)
            self.bus.mincv = await srv.add_path(
                "/System/MinCellVoltage",
                None,
                gettextcallback=lambda p, v: f"{v:0.3f}V",
            )
            self.bus.mincvi = await srv.add_path("/System/MinVoltageCellId", None)
            self.bus.mincti = await srv.add_path("/System/MinTemperatureCellId", None)
            self.bus.maxcti = await srv.add_path("/System/MaxTemperatureCellId", None)
            self.bus.hcycles = await srv.add_path("/History/ChargeCycles", None)
            self.bus.htotalah = await srv.add_path("/History/TotalAhDrawn", None)
            self.bus.bal = await srv.add_path("/Balancing", None)
            self.bus.okchg = await srv.add_path("/Io/AllowToCharge", 0)
            self.bus.okdis = await srv.add_path("/Io/AllowToDischarge", 0)
            # xx = await srv.add_path('/SystemSwitch',1)

            # alarms
            self.bus.allv = await srv.add_path("/Alarms/LowVoltage", None)
            self.bus.alhv = await srv.add_path("/Alarms/HighVoltage", None)
            self.bus.allc = await srv.add_path("/Alarms/LowCellVoltage", None)
            self.bus.alhc = await srv.add_path("/Alarms/HighCellVoltage", None)
            self.bus.allow = await srv.add_path("/Alarms/LowSoc", None)
            self.bus.alhch = await srv.add_path("/Alarms/HighChargeCurrent", None)
            self.bus.alhdis = await srv.add_path("/Alarms/HighDischargeCurrent", None)
            self.bus.albal = await srv.add_path("/Alarms/CellImbalance", None)
            self.bus.alfail = await srv.add_path("/Alarms/InternalFailure", None)
            self.bus.alhct = await srv.add_path("/Alarms/HighChargeTemperature", None)
            self.bus.allct = await srv.add_path("/Alarms/LowChargeTemperature", None)
            self.bus.alht = await srv.add_path("/Alarms/HighTemperature", None)
            self.bus.allt = await srv.add_path("/Alarms/LowTemperature", None)

            if evt is not None:
                evt.set()
            while True:
                await anyio.sleep(99999)
