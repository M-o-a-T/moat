"""
PID controller.
"""

from __future__ import annotations

from moat.lib.pid import CPID
from moat.micro.cmd.base import BaseCmd

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
    val_in: float | None = None
    split: tuple[float, float, float] | None = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.pid = CPID(cfg)
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
        self.split = s = self.pid.integrate(val, t=t)
        if self.sn is not None:
            RTC[self.sn] = self.pid.state
        return self.pid.sum(s)

    doc_s = dict(
        _d="read state",
        _r=dict(
            state="dict", i="float:last input", o="float:last output", split="tuple:p-i-d output"
        ),
    )

    async def cmd_s(self):
        """
        Returns the current state.
        """
        return dict(
            state=self.pid.get_state(),
            split=self.split,
            i=self.val_in,
            o=self.pid.sum(self.split),
        )
