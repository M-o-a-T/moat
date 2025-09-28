from __future__ import annotations

import contextlib
from functools import cached_property

import asyncdbus.service as dbus
from victron.dbus.utils import wrap_dbus_dict, wrap_dbus_value

from moat.util import attrdict
from moat.conv.steinhart import celsius2thermistor, thermistor2celsius
from moat.dbus import DbusInterface
from moat.util.compat import sleep

from .packet import *


def _t(x):
    if x is None:
        return -1000
    return x


class CellInterface(DbusInterface):
    def __init__(self, cell, dbus):
        self.cell = cell
        super().__init__(dbus, cell.path, "bms")

    @dbus.method()
    def GetData(self) -> "a{sv}":
        return wrap_dbus_dict(self.cell._data)

    @dbus.signal()
    def DataChanged(self) -> "a{sv}":
        return wrap_dbus_dict(self.cell._data)

    @dbus.method()
    def GetConfig(self) -> "a{sv}":
        return wrap_dbus_dict(self.cell.cfg)

    @dbus.method()
    async def GetVoltage(self) -> d:
        h, res = await self.cell.send(RequestCellVoltage())
        if not h.seen:
            return 0
        res[0].to_cell(self.cell)
        return self.cell.voltage

    @dbus.method()
    async def GetTemperature(self) -> dd:
        h, res = await self.cell.send(RequestCellTemperature())
        if not h.seen:
            return (-1000, -1000)
        res[0].to_cell(self.cell)
        return (_t(self.cell.load_temp), _t(self.cell.batt_temp))

    @dbus.method()
    async def GetPIDparams(self) -> uuu:
        return await self.cell.get_pid()

    @dbus.method()
    async def GetPIDpwm(self) -> d:
        h, res = await self.cell.send(RequestBalancePower())
        if not h.seen:
            return -1
        res[0].to_cell(self.cell)
        return self.cell.balance_pwm

    @dbus.method()
    async def SetPIDparams(self, kp: u, ki: u, kd: u) -> b:
        return await self.cell.set_pid(kp, ki, kd)

    @dbus.method()
    def GetTemperatureLimit(self) -> d:
        return _t(self.cell.load_maxtemp)

    @dbus.method()
    async def SetTemperatureLimit(self, data: d) -> b:
        return await self.cell.set_loadtemp_limit(data)

    @dbus.method()
    async def Identify(self) -> b:
        h, _res = await self.cell.send(RequestIdentifyModule())
        return h.seen

    @dbus.method()
    async def SetBalanceVoltage(self, data: d) -> b:
        if data < 0.1:
            await self.cell.set_force_balancing(None)
            return True
        if self.cell.voltage < data:
            return False
        await self.cell.set_force_balancing(data)
        return True

    @dbus.method()
    def GetBalanceVoltage(self) -> d:
        return self.cell.balance_threshold or 0

    @dbus.method()
    def GetConfig(self) -> v:
        return wrap_dbus_value(self.cell.cfg)

    @dbus.method()
    async def SetVoltage(self, data: d) -> b:
        # update the scale appropriately
        c = self.cell
        adj = (data - c.cfg.u.offset) / (c.voltage - c.cfg.u.offset)
        c.cfg.u.scale *= adj
        await c.update_cell_config()

        # TODO move this to a config update handler
        c._voltage = data
        c.voltage_min = (c.voltage_min - c.cfg.u.offset) * adj + c.cfg.u.offset
        c.voltage_max = (c.voltage_max - c.cfg.u.offset) * adj + c.cfg.u.offset
        return True

    @dbus.method()
    async def SetVoltageOffset(self, data: d) -> i:
        # update the scale appropriately
        # XXX TODO not stored on the module yet
        c = c.cell
        adj = data - c.cfg.u.offset
        attrdict()
        await c.req.send(["sys", "cfg"], attrdict()._update(c.cfgpath | "u", {"offset": data}))

        # TODO move this to a config update handler
        c.voltage += adj
        c.voltage_min += adj
        c.voltage_max += adj
        return 0


class Cell:
    batt: Battery
    path: str
    nr: int
    cfg: dict
    bcfg: dict
    gcfg: dict

    pid_kp: int = None
    pid_ki: int = None
    pid_kd: int = None

    settingsCached: bool = False
    valid: bool = False
    _voltage: float = None
    voltage_min: float = None
    voltage_max: float = None
    # value from module

    msg_hi: bool = False
    msg_vhi: bool = False
    msg_lo: bool = False
    msg_vlo: bool = False

    load_temp: float = None  # current, on balancer
    batt_temp: float = None  # current, on battery
    load_maxtemp: float = None  # limit

    v_per_ADC: float = None
    n_samples: int = None

    in_balance: bool = False
    balance_pwm: float = None  # percentage of time the balancer is on
    balance_over_temp: bool = False
    balance_threshold: float = None
    balance_forced: bool = False

    board_version: int = None
    code_version: int = None

    # current counter
    balance_Ah: float = None

    # packet counter
    packets_in: int = None
    packets_bad: int = None

    async def set_loadtemp_limit(self, val):
        self.load_maxtemp = val

        pkt = RequestConfig()
        pkt.bypassTempRaw = self.load_maxtemp_raw
        h, _res = await self.send(pkt)
        return h.seen

    async def set_force_balancing(self, val):
        if val is None:
            self.balance_forced = False
            self.balance_threshold = 0
            # will be repaired during the next pass
        else:
            self.balance_forced = True
            self.balance_threshold = val

        h, _res = await self.send(RequestBalanceLevel.from_cell(self))
        self.batt.trigger_balancing()
        return h.seen

    async def get_pid(self):
        h, res = await self.send(RequestReadPIDconfig())
        r = res[0]
        return r.kp, r.ki, r.kd

    async def set_pid(self, kp, ki, kd):
        h, _res = await self.send(RequestWritePIDconfig(kp, ki, kd))
        return h.seen

    async def set_balancing(self, val):
        if self.balance_forced:
            return False
        self.balance_threshold = val
        h, _res = await self.send(RequestBalanceLevel.from_cell(self))
        return h.seen

    async def clear_balancing(self):
        self.balance_threshold = None
        h, _res = await self.send(RequestBalanceLevel.from_cell(self))
        return h.seen

    def __init__(self, batt, path, nr, cfg, bcfg, gcfg):
        self.batt = batt
        self.path = path
        self.nr = nr
        self.cfg = cfg
        self.bcfg = bcfg
        self.gcfg = gcfg

    def __repr__(self):
        return f"‹Cell {self.path} u={0 if self.voltage is None else self.voltage:.3f}›"

    async def config_updated(self):
        pass

    @property
    def req(self):
        return self.batt.ctrl._req

    @property
    def busname(self):
        return self.batt.busname

    async def send(self, pkt):
        return await self.batt.ctrl.send(pkt, start=self.nr)

    async def update_cell_config(self):
        msg = RequestConfig.from_cell(self)
        return await self.send(msg)

    async def run(self):
        dbus = self.batt.ctrl.dbus
        try:
            async with CellInterface(self, dbus) as intf:
                self._intf = intf

                while True:
                    await sleep(99999)

        finally:
            with contextlib.suppress(AttributeError):
                del self._intf

    @cached_property
    def cfg_path(self):
        return self.batt.cfg_path | "cells" | self.nr

    @property
    def v_calibration(self):
        return self.cfg.u.scale

    @v_calibration.setter
    def v_calibration(self, val):
        self.cfg.u.scale = val

    @property
    def _config(self):
        return self.cfg

    @property
    def _data(self):
        res = attrdict()
        if self.voltage:
            res.v = self.voltage
        if self.load_temp is not None:
            res.t_int = self.load_temp
        if self.batt_temp is not None:
            res.t_ext = self.batt_temp
        if self.balance_Ah is not None:
            res.bal_ah = self.balance_Ah
        if self.in_balance:
            res.balancing = self.balance_pwm if self.balance_pwm else 0.001
        else:
            res.balancing = 0
        res.balance_to = self.cfg.u.balance
        return res

    @property
    def voltage(self):
        return self._voltage

    @voltage.setter
    def voltage(self, val):
        if val > 0:
            self._voltage = val
            self.voltage_min = (
                val if self.voltage_min is None else min(self.voltage_min or 9999, val)
            )
            self.voltage_max = max(self.voltage_max or 0, val)
            self.valid = True

    @property
    def internal_temp_raw(self) -> int:
        if self.cfg.load.b is None:
            return None
        return celsius2thermistor(self.cfg.load.b, self.load_temp)

    @internal_temp_raw.setter
    def internal_temp_raw(self, val):
        if self.cfg.load.b is None:
            return None
        self.load_temp = thermistor2celsius(self.cfg.load.b, val)

    @property
    def load_maxtemp_raw(self) -> int:
        if self.cfg.load.b is None:
            return None
        return celsius2thermistor(self.cfg.load.b, self.load_maxtemp)

    @load_maxtemp_raw.setter
    def load_maxtemp_raw(self, val):
        if self.cfg.load.b is None:
            return None
        self.load_maxtemp = thermistor2celsius(self.cfg.load.b, val)

    @property
    def external_temp_raw(self) -> int:
        if self.cfg.batt.b is None:
            return None
        return celsius2thermistor(self.cfg.batt.b, self.batt_temp)

    @external_temp_raw.setter
    def external_temp_raw(self, val):
        if self.cfg.batt.b is None:
            return None
        self.batt_temp = thermistor2celsius(self.cfg.batt.b, val)

    def _volt2raw(self, val):
        if val is None or self.n_samples is None:
            return 0
        return int(
            (val - self.cfg.u.offset) / self.v_per_ADC * self.n_samples / self.v_calibration,
        )

    def _raw2volt(self, val):
        if val is None or self.cfg.u.samples is None or val == 0:
            return None
        return val * self.v_per_ADC / self.cfg.u.samples * self.v_calibration + self.cfg.u.offset

    @property
    def balance_threshold_raw(self):
        return self._volt2raw(self.balance_threshold)

    @balance_threshold_raw.setter
    def balance_threshold_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.balance_threshold = val

    @property
    def balance_config_threshold_raw(self):
        return self._volt2raw(self.cfg.u.balance)

    @balance_config_threshold_raw.setter
    def balance_config_threshold_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.cfg.u.balance = val

    @property
    def balance_threshold_raw(self):
        return self._volt2raw(self.balance_threshold)

    @balance_threshold_raw.setter
    def balance_threshold_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.balance_threshold = val

    @property
    def voltage_raw(self):
        return self._volt2raw(self._voltage)

    @voltage_raw.setter
    def voltage_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.voltage = val

    @property
    def balance_current_count(self):
        if not self.cfg.load.r:
            return None
        # not needed, but the reverse of the setter
        return self._volt2raw(self.balance_Ah * self.cfg.load.r * 3600000.0)

    @balance_current_count.setter
    def balance_current_count(self, val):
        if not self.cfg.load.r:
            return
        # the raw value is the cell voltage ADC * voltageSamples, added up once per millisecond.
        # Thus here we divide by resistance and 1000*3600 (msec in an hour) to get Ah.
        self.balance_Ah = self._raw2volt(val) / self.cfg.load.r / 3600000.0

    @property
    def load_resistence_raw(self):
        return int(self.cfg.load.r * 64 + 0.5)

    @load_resistence_raw.setter
    def load_resistence_raw(self, value):
        self.cfg.load.r = value / 64
