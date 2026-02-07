"""
"Slow" PWM handler.

This is intended for slow devices like a thermically controlled heating
valve, where switching every five seconds or so works perfectly well.
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
        base: the maximum value for the ratio.
        init: initial value (defaults to `min`)
        so: stream_out: Flag whether to stream the pin value
        vmin: Minimum value. Turn off if below.
        vmax: Maximum value. Turn off if above.
        resync: Time (ms) to force output on/off when transitioning from
                outside vmin/vmax back into range. Limited by actual off time.

        ramp(dict): Ramp-up settings.
        ramp.val(float): Threshold. Force the PWM value to be at least this
                         large while the float returned from calling *path*
                         is less than *dest*.
        ramp.path(Path): Path to read periodically while ramp-up is in effect.
        ramp.dest(float): The value which the result from *path* needs to reach
                          in order to leave ramp-up.

    The input must be in [0..base]; the output is controlled so that
    ``t_on/(t_on+t_off) = val/base``, given that ``min <= t_on,t_off <= max``
    and one of t_on and t_off are equal to `min`. (Thus when ``val=base/2``,
    both are.)

    If val is too low (or too high) such that this constraint can no longer
    be satisfied, the output is turned off (or on) permanently.

    When resync is set, transitioning from below vmin back into range forces
    the output ON for min(resync, time_was_off) milliseconds first. Similarly,
    transitioning from above vmax forces the output OFF for that duration.
    If the value goes back out of range during resync, resync is cancelled.
    """

    t_last = 0
    t_on: int = 0
    t_off: int = 0
    is_on: bool = False

    value: int = 0  # must be in range 0..base
    init: int = 0  # initial value
    min: int = 500  # milliseconds
    max: int = 100000  # milliseconds
    vmin: int | None = None
    vmax: int | None = None
    resync: int = 0  # resync duration in milliseconds
    base: int = 1000  # max for value
    evt: Event
    ps: Msg  # Data stream to the pin
    force: int | None = None

    # Resync state tracking
    _out_time: int = 0  # accumulated out-of-range time (capped at resync)
    _out_on: bool | None = None  # True=above vmax (on), False=below vmin (off), None=in range
    _resync_left: int = 0  # remaining resync time
    _resync_on: bool | None = None  # forced state during resync (True=on, False=off)
    _last_measure: int = 0  # timestamp of last _measure call

    doc = dict(
        _c=dict(
            _d="Slow PWM",
            pin="path:output cmd",
            max="int:max T(100000,ms)",
            min="int:min T(500,ms)",
            vmax="float:max value",
            vmin="float:min value",
            resync="int:resync time(0,ms)",
            base="float:input range 0...(1000)",
            init="float:initial value",
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
        self.vmin = cfg.get("vmin", self.vmin)
        self.vmax = cfg.get("vmax", self.vmax)
        self.resync = cfg.get("resync", self.resync)
        self.base = cfg.get("base", self.base)
        self.so = self.cfg.get("so", False)

    async def reload(self):
        "reload from config"
        self._load()
        await super().reload()

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pin = self.root.sub_at(self.cfg["pin"], cmd=not self.so)
        if await self.pin.rdy_():
            raise StoppedError("pin")
        self.set_times(self.cfg.get("init", self.min))

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
                    await self._delay(dly)
            finally:
                await self.ps.send(False)

    async def _measure(self, now: int) -> int | None:
        """
        Check whether it's time to switch.

        Returns: delay until the next switch, or ``None`` for
        "until the value is changed".
        """
        # Track time delta for out-of-range accumulation
        measure_td = ticks_diff(now, self._last_measure)
        self._last_measure = now

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

        # Accumulate out-of-range time (capped at resync)
        if self._out_on is not None and self.resync > 0:
            self._out_time = min(self.resync, self._out_time + measure_td)

        # Check if we're in resync mode
        if self._resync_left > 0:
            self._resync_left -= measure_td
            if self._resync_left <= 0:
                # Resync complete, resume normal operation
                self._resync_left = 0
                self._resync_on = None
                self.t_last = now  # reset timing for normal PWM
                td = 0  # recalculate since t_last changed
            else:
                # Still in resync: force the output state
                if self.is_on != self._resync_on:
                    await self.ps.send(self._resync_on)
                    self.is_on = self._resync_on
                return self._resync_left

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
            r = a * (base - val) // val  # times are integer msec
            b = min(b, r)

        return (b, a) if rev else (a, b)

    def set_times(self, val: float, force: bool = False):
        """
        Change the on/off ratio to approximately ``val/base``.
        """
        if val is None:
            if not force:
                raise ValueError(val)
            self.force = None
            return

        if val < 0 or val > self.base:
            raise ValueError(val, self.base)
        if force:
            self.force = val
        else:
            self.value = val

        if self.vmin is not None and val <= self.vmin:
            t_on, t_off = (0, self.max)
        elif self.vmax is not None and val >= self.vmax:
            t_on, t_off = (self.max, 0)
        else:
            t_on, t_off = self.calc_times(val)

        is_below_vmin = t_on == 0 and t_off != 0
        is_above_vmax = t_off == 0 and t_on != 0
        is_in_range = t_on != 0 and t_off != 0

        # Handle resync transitions
        if self.resync > 0:
            if is_in_range:
                if self._out_on is not None and self._out_time > 0:
                    # Transition from out-of-range to in range: start resync
                    # _resync_on is opposite of _out_on: was off -> resync on, was on -> resync off
                    self._resync_left = self._out_time
                    self._resync_on = not self._out_on
                self._out_on = None
                self._out_time = 0
            else:
                # Going out of range: cancel any resync, set out state
                self._resync_left = 0
                self._resync_on = None
                if is_below_vmin:
                    if self._out_on is not False:
                        self._out_on = False
                        self._out_time = 0
                elif is_above_vmax:
                    if self._out_on is not True:
                        self._out_on = True
                        self._out_time = 0

        self.t_on = t_on
        self.t_off = t_off

        td = ticks_diff(ticks_ms(), self.t_last)
        if td >= (t_on if self.is_on else t_off):
            self.evt.set()

    doc_w = dict(
        _d="change",
        _0="float|None:new value",
        f="bool:forced value",
        _i=dict(_0="float:new value"),
    )

    async def stream_w(self, msg: Msg):
        "change ratio"
        if msg.can_stream:
            async with msg.stream_in() as md:
                async for m in md:
                    self.set_times(m[0], msg.get("f", False))
        else:
            self.set_times(msg[0], msg.get("f", False))

    doc_s = dict(
        _d="read state",
        _r=dict(
            on="int:t_on",
            off="int:t_off",
            p="bool:state",
            t="int:time until next change",
        ),
    )

    @property
    def val(self) -> float:
        """
        The current value.
        """
        if self.force is not None:
            return self.force
        return self.value

    async def cmd_r(self) -> float:
        """
        Returns the current value.
        """
        return self.val

    async def cmd_s(self) -> Mapping:
        """
        Returns the current state.
        """
        now = ticks_ms()
        res = dict(
            on=self.t_on,
            off=self.t_off,
            p=self.is_on,
            val=self.value,
        )
        if self.force is not None:
            res["force"] = self.force
        if self._resync_left > 0:
            res["resync"] = self._resync_left
            res["resync_on"] = self._resync_on
        elif self._out_on is not None:
            res["out_time"] = self._out_time
        elif self.t_on and self.t_off:
            res["t"] = (self.t_on if self.is_on else self.t_off) - ticks_diff(now, self.t_last)
        return res
