"""
"Slow" PWM handler.

This is intended for slow devices like a thermically controlled heating
valve, where switching every five seconds or so works perfectly well.
"""

from __future__ import annotations

from moat.util import Path
from moat.lib.codec.errors import StoppedError
from moat.micro.cmd.base import BaseCmd
from moat.util.compat import (
    Event,
    L,
    TimeoutError,  # noqa:A004
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


class _Send:
    # A null context that delegates its .send method to the wrapped destination
    def __init__(self, dest):
        self.dest = dest

    def send(self, *a, **kw):
        return self.dest(*a, **kw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        return None


class PWM(BaseCmd):
    """
    A PWM is an output pin that changes periodically.

    Config:
    - pin: the hardware output we're controlling. Path to the write method.
    - min: Minimum time between switching, milliseconds
    - max: Maximum time between switching, milliseconds
    - base: the maximum value for the ratio.
    - init: initial value (defaults to `min`)
    - so: stream_out: Flag whether to stream the pin value

    The input must be in [0..base]; the output is controlled so that
    `t_on/(t_on+t_off) = val/base`, given that `min <= t_on,t_off <= max`
    and one of t_on and t_off are equal to `min`. (Thus when `val=base/2`,
    both are.)

    If val is too low (or too high) such that this constraint can no longer
    be satisfied, the output is turned off (or on) permanently.
    """

    t_last = 0
    t_on: int = 0
    t_off: int = 0
    is_on: bool = False

    value: int = 0  # must be in range 0..base
    init: int = 0  # initial value
    min: int = 500  # milliseconds
    max: int = 100000  # milliseconds
    base: int = 1000  # max for value
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
        self.pin = self.root.sub_at(self.cfg["pin"])
        if await self.pin.rdy_():
            raise StoppedError("pin")
        self.set_times(self.cfg.get("init", self.min))

    async def task(self):  # noqa:D102
        async with (
            _Send(self.pin) if not self.cfg.get("so", False) else self.pin.stream_out()
        ) as self.ps:
            try:
                if L:
                    self.set_ready()
                self.t_last = ticks_ms()
                self.is_on = False
                await self.ps.send(False)

                while True:
                    dly = await self._measure(ticks_ms())
                    await self._delay(dly)
            finally:
                await self.ps.send(False)

    async def _measure(self, now: int) -> int | None:
        """
        Check whether it's time to switch.

        Returns: delay until the next switch, or ``None`` for
        "until the value is changed".
        """
        td = ticks_diff(now, self.t_last)

        async def _sw(state: bool) -> int:
            nonlocal now

            if self.is_on != state:
                await self.ps.send(state)
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

    async def _delay(self, dly: int | None) -> None:
        """
        Delay for @dly milliseconds, or until the event is set.
        """
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

    def calc_times(self, val: int) -> tuple[int, int]:
        """
        Calculate the t_on/t_off tuple so that
        ``t_on/(t_on+t_off) == val/base`` and ``min <= t_{on,off} <= max``.

        If that ratio falls below ``min/(min+max)``, switch off entirely
        (t_on=0). Likewise, turn on when the ratio is too high.
        """
        rev = False

        a = self.min
        b = self.max
        base = self.base

        if val * 2 > base:
            rev = True
            val = base - val

        # a/(a+b) is the minimum ratio. Below half that we switch off,
        # i.e. val/base < a/(a+b)/2 -- reordered to avoid division.
        if val * (a + b) * 2 < a * base:
            a = 0
        else:
            # a/(a+b) == val/base; solve for b
            # the test above prevents val from being zero
            r = a * (base - val) / val
            b = min(b, r)

        return (b, a) if rev else (a, b)

    def set_times(self, val: int):
        """
        Change the on/off ratio to approximate ``v/base``.
        """
        t_on, t_off = self.calc_times(val)
        self.t_on = t_on
        self.t_off = t_off

        td = ticks_diff(ticks_ms(), self.t_last)
        if td >= (t_on if self.is_on else t_off):
            self.evt.set()

    doc_w = dict(_d="change", _0="float:new value", _i=dict(_0="float:new value"))

    async def stream_w(self, msg: Msg):
        "change ratio"
        if msg.can_stream:
            async with msg.stream_in() as md:
                async for m in md:
                    self.set_times(m[0])
        else:
            self.set_times(msg[0])

    doc_s = dict(
        _d="read state",
        _r=dict(
            on="int:t_on",
            off="int:t_off",
            p="bool:state",
            t="int:time until next change",
        ),
    )

    async def cmd_s(self):
        """
        Returns the current state.
        """
        res = dict(
            on=self.t_on,
            off=self.t_off,
            p=self.is_on,
        )
        if self.t_on and self.t_off:
            res["t"] = (self.t_on if self.is_on else self.t_off) - ticks_diff(
                ticks_ms(), self.t_last
            )
        return res
