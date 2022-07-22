import asyncdbus.service as dbus
from dataclasses import dataclass
from ..conv.steinhart import thermistor2celsius, celsius2thermistor
from moat.util import attrdict, combine_dict
from victron.dbus.utils import wrap_dbus_value, wrap_dbus_dict

class Cell(dbus.ServiceInterface):
    batt:"Battery"
    path:str
    nr: int
    cfg:dict
    bcfg:dict
    gcfg:dict

    settingsCached:bool = False
    valid:bool = False
    _voltage:float = None
    voltage_min:float = None
    voltage_max:float = None
    # value from module

    load_temp:float = None
    batt_temp:float = None

    v_per_ADC:float = None
    n_samples:int = None

    in_balance:bool = False
    balance_pwm:float = None  # percentage of time the balancer is on
    balance_over_temp:bool = False

    board_version:int = None
    code_version:int = None

    # current counter
    balance_Ah:float = None

    # packet counter
    packets_in:int = None
    packets_bad:int = None

    def __init__(self, batt, path, nr, cfg, bcfg, gcfg):
        self.batt = batt
        self.path = path
        self.nr = nr
        self.bcfg = bcfg
        self.gcfg = gcfg

        super().__init__("org.m_o_a_t.bms")
        self.cfg = combine_dict(cfg, bcfg.default, cls=attrdict)

    def __repr__(self):
        return f"‹Cell {self.path} u={self.voltage}›"

    async def export(self, bus):
        self._bus = bus
        await bus.export(self.path, self)

    async def unexport(self):
        if self._bus is not None:
            await self._bus.unexport(self.path, self)
            self._bus = None

    async def send(self, pkt):
        await self.ctrl.send(pkt,start=self.nr)

    async def send_update(self):
        msg = RequestConfig.from_cell(self)
        await self.send(msg)

    @dbus.method()
    async def GetData(self) -> 'a{sv}':
        return wrap_dbus_dict(self._data)

    @dbus.signal()
    def DataChanged(self) -> 'a{sv}':
        return wrap_dbus_dict(self._data)

    @dbus.method()
    async def GetConfig(self) -> 'a{sv}':
        return wrap_dbus_dict(self.cfg)

    @dbus.method()
    async def GetVoltage(self) -> 'd':
        return self.voltage

    @dbus.method()
    async def GetCalibration(self) -> 'd':
        return self.v_calibration

    @dbus.method()
    async def SetCalibration(self, data: 'd') -> 'i':
        od, self.cfg.v_calibration = self.cfg.v_calibration, d
        self._voltage = self._voltage * d/od
        self.voltage_min = self.voltage_min * d/od
        self.voltage_max = self.voltage_max * d/od
        await self.send_update()
        return 0

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
            self.voltage_min = val if self.voltage_min is None else min(self.voltage_min or 9999, val)
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
            return None
        return (val - self.cfg.u.offset) / self.v_per_ADC * self.n_samples / self.v_calibration

    def _raw2volt(self, val):
        if val is None or self.cfg.u.samples is None:
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
        return self._volt2raw(self.balance_Ah*self.cfg.load.r*3600000.0)

    @balance_current_count.setter
    def balance_current_count(self, val):
        if not self.cfg.load.r:
            return
        # the raw value is the cell voltage ADC * voltageSamples, added up once per millisecond.
        # Thus here we divide by resistance and 1000*3600 (msec in an hour) to get Ah.
        self.balance_Ah = self._raw2volt(val)/self.cfg.load.r/3600000.0

    @property
    def load_resistence_raw(self):
        return int(self.cfg.load.r * 64 + 0.5)

    @load_resistence_raw.setter
    def load_resistence_raw(self, value):
        self.cfg.load.r = value/64
