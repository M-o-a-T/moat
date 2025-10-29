"""
A serially-connected cell.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.ems.battery._base import BaseCell
from moat.ems.battery.conv.steinhart import celsius2thermistor, thermistor2celsius

from .packet import (
    RequestBalanceCurrentCounter,
    RequestBalanceLevel,
    RequestBalancePower,
    RequestConfig,
    RequestReadPIDconfig,
    RequestReadSettings,
    RequestTemperature,
    RequestVoltages,
    RequestWritePIDconfig,
)


class Cell(BaseCell):
    """
    Direct (inefficient!) interface to a single serially-connected cell.

    @comm: BattComm instance
    @i: cell number there

    This BaseCell translates commands to Comm requests.
    """

    code_version = None
    board_version = None
    v_per_ADC = None
    v_calibration = None
    b_coeff_ext = None
    b_coeff_bal = None
    external_B = None
    n_samples = None

    in_balance = None
    balance_over_temp = None
    packets_in = None
    packets_bad = None
    balance_current_count = None
    bal_power = None

    v_now = None
    batt_temp = None
    load_temp = None
    load_maxtemp = None
    load_volt = None  # balance down up to here

    def __init__(self, cfg):
        super().__init__(cfg)
        if "pid" not in self.cfg:
            self.cfg.pid = attrdict()
        if "load" not in self.cfg:
            self.cfg.load = attrdict()

    def _raw2volt(self, val):
        if val is None or self.cfg.u.samples is None or val == 0:
            return None
        return val * self.v_per_ADC / self.cfg.u.samples * self.v_calibration + self.cfg.u.offset

    def _volt2raw(self, val):
        if val is None or self.n_samples is None or val == 0:
            return 0
        return int(
            (val - self.cfg.u.offset) / self.v_per_ADC * self.n_samples / self.v_calibration,
        )

    def m_temp(self, msg):  # noqa:D102
        self.batt_temp = thermistor2celsius(self.b_coeff_ext, msg.extRaw)
        self.load_temp = thermistor2celsius(self.b_coeff_bal, msg.intRaw)

    def m_settings(self, msg):  # noqa:D102
        self.code_version = msg.gitVersion
        self.board_version = msg.boardVersion
        self.b_coeff_ext = msg.BCoeffInternal
        self.b_coeff_bal = msg.BCoeffExternal
        self.v_per_ADC = msg.mvPerADC / 1000 / 64
        self.v_calibration = msg.voltageCalibration
        self.n_samples = msg.numSamples

        self.load_maxtemp = thermistor2celsius(self.b_coeff_bal, msg.bypassTempRaw)
        self.load_volt = self._raw2volt(msg.bypassVoltRaw)
        self.load_resist = msg.loadResRaw / 16

    doc_param = dict(_d="read params", _r="dict[dict]:various parameters")

    async def cmd_param(self):  # noqa:D102
        return dict(
            typ="diy",
            v=dict(c=self.code_version, b=self.board_version),
            bal=dict(t=self.load_maxtemp, r=self.load_resist),
            u=dict(adc=self.v_per_ADC, cal=self.v_calibration, n=self.n_samples),
            pid=self.cfg.pid,
        )

    async def setup(self):  # noqa:D102
        await super().setup()
        self.comm = self.root.sub_at(self.cfg["comm"], cmd=True)
        res = (await self.comm(p=RequestReadSettings(), s=self.cfg.pos))[0]
        self.m_settings(res)

    doc_u = dict(_d="read Vcell", _r="float")

    async def cmd_u(self):
        "read cell voltage"
        if self.val_u is not None:
            return self.val_u
        res = (await self.comm(p=RequestVoltages(), s=self.cfg.pos))[0]
        return self._raw2volt(res.voltRaw & 0x1FFF)

    def m_volt(self, msg):  # noqa:D102
        self.in_balance = bool(msg.voltRaw & 0x8000)
        self.balance_over_temp = bool(msg.voltRaw & 0x4000)
        vRaw = msg.voltRaw & 0x1FFF
        if vRaw:
            self.v_now = self._raw2volt(vRaw)
        # msg.bypassRaw: legacy, unused

    doc_t = dict(_d="read Tcell", _r="float:degC")

    async def cmd_t(self):
        "read cell temperature"
        if self.load_temp is None:
            res = (await self.comm(p=RequestTemperature(), s=self.cfg.pos))[0]
            res.to_cell(self)
        return self.load_temp

    async def cmd_tb(self):
        "read balancer temperature"
        if self.batt_temp is None:
            res = (await self.comm(p=RequestTemperature(), s=self.cfg.pos))[0]
            res.to_cell(self)
        return self.batt_temp

    def m_pid(self, msg):  # noqa:D102
        self.cfg.pid.p = msg.kp
        self.cfg.pid.i = msg.ki
        self.cfg.pid.d = msg.kd

    doc_calib = dict(
        _d="Calibrate (read if no data)", _r="dict:current data", vcal="float:degC", t=""
    )

    async def cmd_calib(self, vcal=None, t=None, v=None):  # noqa:D102
        if vcal is not None:
            self.v_calibration = vcal
        if t is not None:
            self.load_temp = t
        if v is not None:
            self.load_volt = v
        if vcal is None and t is None and v is None:
            return dict(vcal=self.v_calibration, t=self.load_temp, v=self.load_volt)
        else:
            await self.comm(
                p=RequestConfig(
                    self.v_calibration,
                    celsius2thermistor(self.b_coeff_bal, self.load_temp),
                    self._volt2raw(self.load_volt),
                ),
                s=self.cfg.pos,
            )

    doc_pid = dict(
        _d="r/w PID values", _r="dict:current data", p="float:P", i="float:I", d="float:D"
    )

    async def cmd_pid(self, **pid):
        "get/set the balancer PID values"
        if pid:
            self.cfg.pid.update(pid)
            await self.comm(p=RequestWritePIDconfig(**self.cfg.pid), s=self.cfg.pos)
        if len(self.cfg.pid != 3):
            res = (await self.comm(p=RequestReadPIDconfig(), s=self.cfg.pos))[0]
            self.m_pid(res)
        return self.cfg.pid

    doc_bd = dict(_d="balance down", _r="dict:current state", thr="float:thresholdV")

    async def cmd_bd(self, thr=None):
        """
        Balance down: set the balancer level; get balancer level and current PWM power
        """
        if thr is not None:
            await self.comm(p=RequestBalanceLevel(self._volt2raw(thr)), s=self.cfg.pos)
            self.bal_level = thr
            return

        if self.bal_power is None:
            res = (await self.comm(p=RequestBalancePower(), s=self.cfg.pos))[0]
            self.m_bal_power(res)
        return dict(p=self.bal_power, thr=self.bal_level)

    def m_bal_power(self, msg):  # noqa:D102
        self.bal_power = msg.pwm / 255

    doc_bd_sum = dict(_d="balance sum", _r="int:charge count")

    async def cmd_bd_sum(self):
        "get current counter"
        res = (await self.comm(p=RequestBalanceCurrentCounter(), s=self.cfg.pos))[0]
        return res.counter
