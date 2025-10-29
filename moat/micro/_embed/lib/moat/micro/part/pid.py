"""
PID controller.
"""

from __future__ import annotations

from moat.util import Path
from moat.lib.pid import CPID
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import ticks_diff, ticks_ms

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict
try:
    from moat.micro.rtc import state as RTC
except ImportError:
    from moat.micro.test.rtc import state as RTC


class PID(BaseCmd):
    """
    A PID controller periodically (we hope) receives an input value, and
    returns an output to adjust the input.

    - min, max: output value boundaries
    - p: proportional gain
    - i: integral gain
    - d: differential gain
    - tf: first-order filter time constant for the differential, in seconds
    - state: name of our state storage (in RTC).

    t should be larger than the interval between inputs.
    """

    pid: CPID
    sn: str | None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.pid = CPID(cfg)
        if not isinstance(cfg.get("pin", None), (tuple, list, Path)):
            raise ValueError("Pin not set")  # noqa:TRY004
        self.sn = sn = cfg.get("state", None)
        if sn is not None and sn in RTC:
            data = RTC[sn]
            self.pid.set_state(**data)
            setpoint = data.get("setpoint")
            if setpoint is not None:
                self.pid.setpoint(setpoint)

    def cmd_sr(self) -> attrdict:
        "Read the current state"
        return self.pid.state

    def cmd_sw(self, t: int | None, e: float | None, i: float | None, **_kw):
        "Update the PID state."
        self.pid.set_state(t, e, i)

    #   async def setup(self):
    #       await super().setup()

    #   async def run(self):
    #       async with self.pin.w.stream_out() as self.ps:
    #           try:
    #               self.t_last = ticks_ms()
    #               self.is_on = False
    #               await self.ps.send(False)

    #               while True:
    #                   dly = await self._measure(ticks_ms())
    #                   await self._delay(dly)
    #           finally:
    #               await self.ps.send(False)

    doc_w = dict(_d="step", _0="float:current value", _r="float:new output")

    async def cmd_w(self, val: float, t: int | None = None) -> float:
        """
        Run a PID step.
        """
        val = self.pid(val, t=t)
        if self.sn is not None:
            RTC[self.sn] = self.pid.state
        return val

    doc_s = dict(
        _d="read state",
        _r=dict(
            a="int:t_on",
            b="int:t_off",
            p="bool:state",
            t="int:time since last change",
        ),
    )

    async def cmd_s(self):
        """
        Returns the current state.
        """
        p = await self.is_on
        return dict(
            a=self.t_on,
            b=self.t_off,
            p=p,
            t=ticks_diff(ticks_ms(), self.t_last),
        )
