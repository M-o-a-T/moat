"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import logging
from math import exp

from moat.util import pos2val, val2pos
from moat.ems.battery._base import BalBaseCell
from moat.util.compat import sleep_ms

logger = logging.getLogger(__name__)


class Cell(BalBaseCell):
    """
    Mock battery cell.

    Its nominal charge is 0…1, capacity in amp-sec.

    The voltages are linear between u.ext, plus a power term when exceeding
    that.

    A configuration that replicates a LiFePo4 cell, *very* approximately::

        c: 0.5
        t: 25
        cap: 2000
        i:
          dis: -1  # balancer discharge current
          chg: 0  # TODO
        lim:
          t:
            abs:
              min: 0
              max: 45
            ext:
              min: 10
              max: 40
          c:
            min: 0.2
            max: 0.9
          p:  # exponent when 'ext' limit is exceeded
            min: 2
            max: 3
          u:
            abs:
              min: 2.5
              max: 3.65
            std:
              min: 2.6
              max: 3.55
            ext:
              min: 2.9
              max: 3.4
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self._c = cfg["c"]
        self._t = cfg["t"]
        self._tb = 25
        self.t_env = 25

    async def set_dis(self):
        "set discharger. No-op since we can use .vdis directly."
        pass

    doc_c = dict(_d="get/set charge", c="float:new charge", _r="float:current charge")

    async def cmd_c(self, c: float | None = None) -> float:
        "get/set the current charge"
        if c is not None:
            self._c = c
        return self._c

    doc_u = dict(_d="get voltage", _r="float:voltage")

    async def cmd_u(self, c: float | None = None) -> float:
        """
        return the current voltage.

        If @c is set, return the voltage the cell would have if its current charge was c.
        """
        li = self.cfg["lim"]
        liu = li["u"]
        if c is None:
            c = self._c
        up = val2pos(li["c"]["min"], c, li["c"]["max"])
        if up < 0:
            fx = val2pos(li["c"]["min"], c, 0) ** li["p"]["min"]
            u = pos2val(liu["ext"]["min"], fx, liu["abs"]["min"])
        elif up > 1:
            fx = val2pos(li["c"]["max"], c, 1) ** li["p"]["max"]
            u = pos2val(liu["ext"]["max"], fx, liu["abs"]["max"])
        else:
            u = pos2val(liu["ext"]["min"], up, liu["ext"]["max"])
        return u

    doc_te = dict(_d="get/set env temp", c="float:new temp", _r="float:current temp")

    async def cmd_te(self, t=None) -> float:
        "gets/sets the environment temperature"
        if t is None:
            return self.t_env
        self.t_env = t

    doc_t = dict(_d="get balance temp", _r="float:current temp")

    async def cmd_t(self):
        "returns the balancer resistor temperature"
        return self._t

    doc_tb = dict(_d="get battery temp", _r="float:current temp")

    async def cmd_tb(self):
        "returns the battery temperature"
        return self._tb

    doc_add_p = dict(_d="add energy", p="float:watts", t="float:seconds")

    async def cmd_add_p(self, p, t):
        "add energy to the battery: @p watts for @t msec"
        # watt seconds
        self._c += p * t / self.cfg["cap"] / 1000

        # time takes heat away, Charge+Discharge adds it
        self._t += (self.t_env - self._t) * (1 - exp(-t / 10000)) + abs(p) * t / 100000 * (
            1 if p > 0 else 0.5
        )

    async def task(self):
        self.set_ready()

        while True:
            await sleep_ms(100)
            if self.vdis:
                u = await self.cmd_u()
                if u > self.vdis:
                    await self.cmd_add_p(u * self.cfg["i"]["dis"], 100)

            if self.vchg:
                u = await self.cmd_u()
                if u < self.vchg:
                    await self.cmd_add_p(u * self.cfg["i"]["chg"], 100)

    doc_bal_set = dict(
        _d="set balancer",
        pwm="any:PWM data",
        b="bool:in balance",
        f="nool:bal forced",
        ot="bool:balancer overtemp",
        th="float:bal temp threshold",
    )

    async def cmd_bal_set(self, b=None, f=None, ot=None, pwm=None, th=None):
        if pwm is not None:
            self.balance_pwm = pwm
        if ot is not None:
            self.balance_over_temp = ot
        if f is not None:
            self.balance_forced = f
        if th is not None:
            self.balance_threshold = th
        if b is not None:
            self.in_balance = b


class DiyBMSCell(Cell):
    bc_i = 1000
    bc_e = 2000
    v_per_ADC = 0.001
    n_samples = 3
    v_calibration = 1.0
    v_offset = 0

    doc_b_coeff = dict(_d="get coef", _r=["float:i", "float:e"])

    async def cmd_b_coeff(self):
        return self.bc_i, self.bc_e

    doc_v = dict(_d="calc raw volt", _0="float:voltage", _r="int:value")

    async def cmd_v2raw(self, val):
        if val is None or self.n_samples is None:
            return 0
        return int((val - self.v_offset) / self.v_per_ADC * self.n_samples / self.v_calibration)

    doc_raw = dict(_d="calc real volt", _r="float:voltage", _0="int:value")

    async def cmd_raw2v(self, val):
        if val is None or self.cfg.u.samples is None or val == 0:
            return None
        return val * self.v_per_ADC / self.cfg.u.samples * self.v_calibration + self.cfg.u.offset

    doc_settings = dict(
        _d="get settings",
        _r=dict(
            vpa="float:vol per ADC tick", ns="int:n samples", vcal="float:volt caibration factor"
        ),
    )

    async def cmd_settings(self):
        return dict(vpa=self.v_per_ADC, ns=self.n_samples, vcal=self.v_calibration)
