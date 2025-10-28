"""
More common code
"""

from __future__ import annotations

from moat.util import Path
from moat.lib.codec.errors import StoppedError
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Event, ticks_diff, ticks_ms, wait_for_ms

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


class PWM(BaseCmd):
    """
    A PWM is an output pin that changes periodically.

    - pin: how to talk to the actual hardware output
    - ratio: on/off, between zero (all off) and one (all on).
    - min: Minimum time between switching
    - max: Maximum time between switching

    If the ratio exceeds min/2/max, it is set zo zero. Likewise for max.
    """

    t_last = 0
    t_on: int = 0
    t_off: int = 0
    is_on: bool = False

    value: int = 0
    min: int = 500  # milliseconds
    max: int = 100000  # milliseconds
    base: int = 1000  # baseline for value
    evt: Event
    ps: Msg  # Data stream to the pin

    def __init__(self, cfg):
        super().__init__(cfg)
        if not isinstance(cfg.get("pin", None), (tuple, list, Path)):
            raise ValueError("Pin not set")  # noqa:TRY004
        self.min = cfg.get("min", self.min)
        self.max = cfg.get("max", self.max)
        self.base = cfg.get("base", self.base)
        self.evt = Event()

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pin = self.root.sub_at(self.cfg.pin)
        if await self.pin.rdy_():
            raise StoppedError("pin")

    async def run(self):  # noqa:D102
        async with self.pin.w.stream_out() as self.ps:
            try:
                self.t_last = ticks_ms()
                self.is_on = False
                await self.ps.send(False)

                while True:
                    dly = await self._measure(ticks_ms())
                    await self._delay(dly)
            finally:
                await self.ps.send(False)

    async def _measure(self, now: int) -> int:
        td = ticks_diff(now, self.t_last)

        async def _sw(state: bool) -> int:
            nonlocal now

            if self.is_on != state:
                await self.ps(state)
                self.is_on = state
                self.t_last = now
            if state:
                return self.t_on if self.t_off else None
            else:
                return self.t_off if self.t_on else None

        dly = None
        if self.t_on == 0:
            # switch off
            dly = await _sw(False) if td >= self.min else self.min - td
        elif self.t_off == 0:
            dly = await _sw(True) if td >= self.min else self.min - td

        elif self.is_on:
            dly = await _sw(False) if td >= self.t_on else self.t_on - td
        else:
            dly = await _sw(True) if td >= self.t_off else self.t_off - td
        return dly

    async def _delay(self, dly: int) -> None:
        if dly is None:
            await self.evt.wait()
            self.evt = Event()
        else:
            try:
                await wait_for_ms(dly, self.evt.wait)
            except TimeoutError:
                pass
            else:
                self.evt = Event()

    def calc_ratio(self, val: int) -> tuple[int, int]:
        "Calculate ratio"
        rev = False

        a = self.min
        b = self.max
        base = self.base

        if (val << 1) > base:
            rev = True
            val = base - val

        # a/(a+b) is the minimum ratio. Below half that we switch off,
        # i.e. val/base < a/(a+b)/2 -- reordered to avoid division.
        if val * (a + b) * 2 < a * base:
            a = 0
        else:
            # a/(a+b) == val/base; solve for b
            b = min(b, a * (base - val) // val)

        return (b, a) if rev else (a, b)

    doc_w = dict(_d="change", _0="float:new value")

    async def cmd_w(self, v: int):
        """
        Change on/off ratio.
        """
        t_on, t_off = self.calc_ratio(v)
        self.t_on = t_on
        self.t_off = t_off

        td = ticks_diff(ticks_ms(), self.t_last)
        if td >= (t_on if self.is_on else t_off):
            self.evt.set()

    async def cmd_r(self):
        """
        Returns the current state, as a mapping.

        v: currently set value
        f: currently forced value
        d: delay until next change (msec) or None
        p: actual pin state
        """
        p = await self.pin.r()
        return dict(
            v=self.value,
            f=self.force,
            p=p,
            d=None if self._delay is None else ticks_diff(ticks_ms(), self.t_last),
        )
