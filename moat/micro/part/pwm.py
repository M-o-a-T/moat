"""
"Slow" PWM handler.

The ``PWM`` part is the timing core: an input in [0..1] is converted into
on/off pulses on a bool output, with configurable min/max durations.

For the higher-level wrapper that handles sync/resync and value scaling,
see {py:mod}`moat.micro.part.control`.
"""

from __future__ import annotations

from moat.lib.codec.errors import StoppedError
from moat.lib.micro import (
    Event,
    L,
    TimeoutError,  # noqa:A004
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)
from moat.lib.path import Path
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg

    from collections.abc import Mapping


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

    Parameters:
        pin: the hardware output we're controlling. Path to the write method.
        min: Minimum time between switching, milliseconds
        max: Maximum time between switching, milliseconds
        so: stream_out: Flag whether to stream the pin value

    The input must be in [0..1]; the output is controlled so that
    ``t_on/(t_on+t_off) = val``, given that ``min <= t_on,t_off <= max``
    and one of t_on and t_off is equal to ``min``. (Thus when ``val=0.5``,
    both are.)

    If ``val`` is too low (or too high) such that this constraint can no
    longer be satisfied, the output is turned off (or on) permanently.
    """

    t_last = 0
    t_on: int = 0
    t_off: int = 0
    is_on: bool = False
    value: float = 0.0
    min: int = 500  # milliseconds
    max: int = 100000  # milliseconds
    so: bool = False
    evt: Event
    ps: Msg

    doc = dict(
        _c=dict(
            _d="Slow PWM",
            pin="path:output cmd",
            max="int:max T(100000,ms)",
            min="int:min T(500,ms)",
            so="bool:stream to pin? (no)",
        )
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        if not isinstance(cfg.get("pin", None), (tuple, list, Path)):
            raise ValueError(f"Pin not set {cfg}")  # noqa:TRY004
        self._load()
        self.evt = Event()

    def _load(self):
        cfg = self.cfg
        self.min = cfg.get("min", self.min)
        self.max = cfg.get("max", self.max)
        self.so = cfg.get("so", False)

    async def reload(self):
        "reload from config"
        self._load()
        await super().reload()

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pin = self.root.sub_at(self.cfg["pin"], cmd=not self.so)
        if await self.pin.rdy_():
            raise StoppedError("pin")
        self.set_times(0.0)

    async def task(self):  # noqa:D102
        async with _Send(self.pin) if not self.so else self.pin.stream_out() as self.ps:
            try:
                if L:
                    self.set_ready()
                self.t_last = ticks_ms()
                self.is_on = False
                await self.ps.send(False)

                while True:
                    dly = await self._measure(ticks_ms())

                    # Delay for @dly milliseconds, or until the event is set.
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

            finally:
                await self.ps.send(False)

    async def _measure(self, now: int) -> int | None:
        """
        Check whether it's time to switch.

        Returns: delay until the next switch, or ``None`` for
        "until the value is changed".
        """
        td = ticks_diff(now, self.t_last)

        async def _sw(state: bool) -> int | None:
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
            dly = await _sw(False) if td >= self.min else int(self.min - td)
        elif self.t_off == 0:
            dly = await _sw(True) if td >= self.min else int(self.min - td)
        elif self.is_on:
            dly = await _sw(False) if td >= self.t_on else int(self.t_on - td)
        else:
            dly = await _sw(True) if td >= self.t_off else int(self.t_off - td)
        return dly

    def calc_times(self, val: float) -> tuple[int, int]:
        """
        Calculate the t_on/t_off tuple so that
        ``t_on/(t_on+t_off) == val`` and ``min <= t_{on,off} <= max``.

        If that ratio falls below ``min/(min+max)``, switch off entirely
        (t_on=0). Likewise, turn on when the ratio is too high.
        """
        rev = False
        a = self.min
        b = self.max

        if val * 2 > 1:
            rev = True
            val = 1 - val

        # a/(a+b) is the minimum ratio. Below half of that we switch off,
        # i.e. val < a/(a+b)/2 -- reordered to avoid division.
        if val * (a + b) * 2 < a:
            a = 0
        else:
            # a/(a+b) == val; solve for b.
            # the test above prevents val from being zero.
            r = int(a * (1 - val) / val)
            b = min(b, r)

        return (b, a) if rev else (a, b)

    def set_times(self, val: float) -> None:
        """
        Change the on/off ratio to approximately ``val``.
        """
        if val < 0 or val > 1:
            raise ValueError(val)
        self.value = val

        t_on, t_off = self.calc_times(val)
        self.t_on = t_on
        self.t_off = t_off

        td = ticks_diff(ticks_ms(), self.t_last)
        if td >= (t_on if self.is_on else t_off):
            self.evt.set()

    doc_w = dict(
        _d="change",
        _0="float:new value [0..1]",
        _i=dict(_0="float:new value [0..1]"),
    )

    async def cmd_w(self, val: float) -> None:
        "change ratio"
        self.set_times(val)

    async def stream_w(self, msg: Msg):
        "change ratio (streaming)"
        async with msg.stream_in() as md:
            async for m in md:
                self.set_times(m[0])

    doc_r = dict(_d="read value", _r="float:current value [0..1]")

    async def cmd_r(self) -> float:
        "Returns the current value."
        return self.value

    doc_s = dict(
        _d="read state",
        _r=dict(
            on="int:t_on",
            off="int:t_off",
            p="bool:state",
            t="int:time until next change",
            val="float:current value",
        ),
    )

    async def cmd_s(self) -> Mapping:
        "Returns the current state."
        now = ticks_ms()
        res: dict[str, object] = dict(
            on=self.t_on,
            off=self.t_off,
            p=self.is_on,
            val=self.value,
        )
        if self.t_on and self.t_off:
            res["t"] = (self.t_on if self.is_on else self.t_off) - ticks_diff(now, self.t_last)
        return res
