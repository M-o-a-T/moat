import asyncdbus.service as dbus
from dataclasses import dataclass
from ..conv.steinhart import thermistor2celsius, celsius2thermistor
from moat.util import attrdict, combine_dict

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
    _v_calibration:float = None

    internal_temp:float = None
    external_temp:float = None

    voltageSamples:int = None
    v_per_ADC:float = None

    in_bypass:bool = False
    bypass_pwm:float = None
    bypass_over_temp:bool = False
    bypass_max_temp:float = None
    bypass_current_threshold:float = None
    bypass_config_threshold:float = None

    load_resistance:float = None
    board_version:int = None
    code_version:int = None

    balance_Ah:float = None
    packets_in:int = None
    packets_bad:int = None

    def __init__(self, batt, path, nr, cfg, bcfg, gcfg):
        self.batt = batt
        self.path = path
        self.nr = nr
        self.cfg = cfg
        self.bcfg = bcfg
        self.gcfg = gcfg

        super().__init__("org.m-o-a-t.bms")
        self.cfg = combine_dict(self.cfg, self.bcfg.default)

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
        return self._data

    @dbus.signal()
    def DataChanged(self) -> 'a{sv}':
        return self._data

    @dbus.method()
    async def GetConfig(self) -> 'a{sv}':
        return self.cfg

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
        return self._v_calibration or self.cfg.v_calibration
    @v_calibration.setter
    def v_calibration(self, val):
        self._v_calibration = val

    @property
    def _config(self):
        return self.cfg

    @property
    def _data(self):
        res = attrdict()
        if self.voltage:
            res.v = self.voltage
        if self.internal_temp is not None:
            res.t_int = self.internal_temp
        if self.internal_temp is not None:
            res.t_ext = self.external_temp
        if self.balance_Ah is not None:
            res.bal_ah = self.balance_Ah
        if self.in_bypass:
            res.balancing = self.bypass_pwm if self.bypass_pwm else 0.001
        else:
            res.balancing = 0
        res.balance_to = self.bypass_current_threshold or self.bypass_config_threshold
        return res

    @property
    def voltage(self):
        return self._voltage

    @voltage.setter
    def voltage(self, val):
        if val > 0:
            self._voltage = val
            self.voltage_min = min(self.voltage_min or 9999, val)
            self.voltage_max = min(self.voltage_max or 0, val)
            self.valid = True
    
    @property
    def internal_temp_raw(self) -> int:
        return celsius2thermistor(self.cfg.b_int, self.internal_temp)

    @internal_temp_raw.setter
    def internal_temp_raw(self, val):
        if self.cfg.b_int is None:
            return
        self.internal_temp = thermistor2celsius(self.cfg.b_int, val)


    @property
    def bypass_temp_raw(self) -> int:
        if self.bypass_B is None:
            return None
        return celsius2thermistor(self.bypass_B, self.bypass_temp)

    @bypass_temp_raw.setter
    def bypass_temp_raw(self, val):
        if self.bypass_B is None:
            return
        self.bypass_temp = thermistor2celsius(self.bypass_B, val)


    @property
    def externalTemp_raw(self) -> int:
        if self.cfg.b_ext is None:
            return None
        return celsius2thermistor(self.cfg.b_ext, self.externalTemp)

    @externalTemp_raw.setter
    def externalTemp_raw(self, val):
        if self.cfg.b_ext is None:
            return
        self.externalTemp = thermistor2celsius(self.cfg.b_ext, val)

    def _volt2raw(self, val):
        if val is None or self.voltageSamples is None:
            return None
        return val / self.VPerADC * self.voltageSamples / self.cfg.v_calibration

    def _raw2volt(self, val):
        if val is None or self.voltageSamples is None:
            return None
        return val * self.VPerADC / self.voltageSamples * self.cfg.v_calibration

    @property
    def balance_current_threshold_raw(self):
        return self._volt2raw(self.balance_current_threshold)

    @balance_current_threshold_raw.setter
    def balance_current_threshold_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.balance_current_threshold = val

    @property
    def balance_config_threshold_raw(self):
        return self._volt2raw(self.balance_config_threshold)

    @balance_config_threshold_raw.setter
    def balance_config_threshold_raw(self, val):
        val = self._raw2volt(val)
        if val is None:
            return
        self.balance_config_threshold = val

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
        if not self.load_resistance:
            return None
        # not needed, but the reverse of the setter
        return self._volt2raw(self.balance_Ah*self.load_resistance*3600000.0)

    @balance_current_count.setter
    def balance_current_count(self, val):
        if not self.load_resistance:
            return
        # the raw value is the cell voltage ADC * voltageSamples, added up once per millisecond.
        # Thus here we divide by resistance and 1000*3600 (msec in an hour) to get Ah.
        self.balance_Ah = self._raw2volt(val)/self.load_resistance/3600000.0

