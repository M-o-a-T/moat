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
        sync_low(dict): Resync settings for low transitions. The
            ``sync_low.threshold`` acts as the minimum value; output is off
            below it.
        sync_high(dict): Resync settings for high transitions. The
            ``sync_high.threshold`` acts as the maximum value; output is on
            above it.
        sync_path(Path): Path to read periodically while resync is active.
        sync_invert(bool): Invert sync_path comparison.

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

    Resync uses ``sync_low``/``sync_high`` to clamp the PWM input when
    transitioning back into range. When the input crosses above
    ``sync_low.threshold``, the PWM is set to at least ``sync_low.input`` and
    resync begins. When the input drops below ``sync_high.threshold``, the PWM
    is set to at most ``sync_high.input``. Resync ends when ``t_sync``
    expires, when the input returns out of range, or when ``t_sync`` is unset
    and the input passes the resync input. While resync is active, ``sync_path``
    can suspend resync based on ``sync_low.bound``/``sync_high.bound``.
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
    force: int | None = None

    sync_low: dict
    sync_high: dict
    sync_invert: bool = False
    sync_path: BaseCmd | None = None

    # Sync/resync state tracking
    _out_mode: str | None = None
    _sync_active: str | None = None
    _sync_left: int | None = None
    _sync_suspended: bool = False
    _sync_next_check: int = 0
    _sync_check_ms: int | None = None
    _last_measure: int = 0  # timestamp of last _measure call

    _d_threshold = dict(
        _d="describes behavior at min/max boundaries",
        bound="float:suspend resync if @sync_path exceeds this",
        t_sync="int:max resync time (s, optional)",
        t_check="int:interval for value check (s, default 10)",
        threshold="float:threshold to start resync, off below/on above",
        input="float:PWM value during resync",
    )

    doc = dict(
        _c=dict(
            _d="Slow PWM",
            pin="path:output cmd",
            max="int:max T(100000,ms)",
            min="int:min T(500,ms)",
            sync_low=_d_threshold,
            sync_high=_d_threshold,
            sync_path="path:value to check",
            sync_invert="bool:checked value inverted WRT input?",
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

    def _load_sync(self, name: str) -> dict:
        cfg = self.cfg.get(name) or {}
        return dict(
            threshold=cfg.get("threshold"),
            input=cfg.get("input"),
            t_sync=cfg.get("t_sync"),
            t_check=cfg.get("t_check", 10),
            bound=cfg.get("bound"),
        )

    def _load(self):
        cfg = self.cfg
        self.min = cfg.get("min", self.min)
        self.max = cfg.get("max", self.max)
        self.base = cfg.get("base", self.base)
        self.so = self.cfg.get("so", False)
        self.sync_invert = cfg.get("sync_invert", False)
        self.sync_low = self._load_sync("sync_low")
        self.sync_high = self._load_sync("sync_high")

    def _load_sync_path(self):
        # Calling `await self.sync_path()` returns the float to check
        # cfg.sync_low.bound or cfg.sync_high.bound against.
        # Must be called after the command is attached (root is available).
        self.sync_path = self.root.sub_at(self.cfg.sync_path) if "sync_path" in self.cfg else None

    async def reload(self):
        "reload from config"
        self._load()
        self._load_sync_path()
        await super().reload()

    async def setup(self):  # noqa:D102
        await super().setup()
        self.pin = self.root.sub_at(self.cfg["pin"], cmd=not self.so)
        if await self.pin.rdy_():
            raise StoppedError("pin")
        self._load_sync_path()
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

    def _sync_cfg(self, mode: str) -> dict:
        return self.sync_low if mode == "low" else self.sync_high

    def _start_resync(self, mode: str, now: int) -> None:
        cfg = self._sync_cfg(mode)
        if cfg.get("input") is None:
            return
        self._sync_active = mode
        t_sync = cfg.get("t_sync")
        self._sync_left = None if t_sync is None else int(t_sync * 1000)
        self._sync_suspended = False
        if self.sync_path is not None and cfg.get("bound") is not None:
            t_check = cfg.get("t_check", 10)
            self._sync_check_ms = int(t_check * 1000)
            self._sync_next_check = now
        else:
            self._sync_check_ms = None
            self._sync_next_check = 0

    def _end_resync(self) -> None:
        self._sync_active = None
        self._sync_left = None
        self._sync_suspended = False
        self._sync_next_check = 0
        self._sync_check_ms = None

    def _select_out_mode(self, val: float) -> str | None:
        low_threshold = self.sync_low.get("threshold")
        if low_threshold is not None and val <= low_threshold:
            return "low"
        high_threshold = self.sync_high.get("threshold")
        if high_threshold is not None and val >= high_threshold:
            return "high"
        return None

    def _sync_value(self, val: float) -> float:
        if self._sync_active == "low":
            resync_input = self.sync_low.get("input")
            if resync_input is not None:
                return max(val, resync_input)
        elif self._sync_active == "high":
            resync_input = self.sync_high.get("input")
            if resync_input is not None:
                return min(val, resync_input)
        return val

    def _apply_value(self, val: float) -> None:
        if self._out_mode == "low":
            t_on, t_off = (0, self.max)
        elif self._out_mode == "high":
            t_on, t_off = (self.max, 0)
        else:
            eff_val = val
            if self._sync_active is not None and not self._sync_suspended:
                eff_val = self._sync_value(val)
            t_on, t_off = self.calc_times(eff_val)

        self.t_on = t_on
        self.t_off = t_off

        td = ticks_diff(ticks_ms(), self.t_last)
        if td >= (t_on if self.is_on else t_off):
            self.evt.set()

    async def _update_sync(self, now: int, measure_td: int) -> None:
        if self._sync_active is None:
            return

        cfg = self._sync_cfg(self._sync_active)
        prior_suspend = self._sync_suspended
        if (
            self._sync_check_ms is not None
            and self.sync_path is not None
            and ticks_diff(now, self._sync_next_check) >= 0
        ):
            value = await self.sync_path()
            bound = cfg.get("bound")
            if bound is not None:
                if self.sync_invert == (self._sync_active == "low"):
                    self._sync_suspended = value < bound
                else:
                    self._sync_suspended = value > bound
            self._sync_next_check = now + self._sync_check_ms

        if self._sync_left is not None and not self._sync_suspended:
            self._sync_left -= measure_td
            if self._sync_left <= 0:
                self._end_resync()
                self._apply_value(self.val)
                return

        if prior_suspend != self._sync_suspended:
            self._apply_value(self.val)

    async def _measure(self, now: int) -> int | None:
        """
        Check whether it's time to switch.

        Returns: delay until the next switch, or ``None`` for
        "until the value is changed".
        """
        measure_td = ticks_diff(now, self._last_measure)
        self._last_measure = now

        await self._update_sync(now, measure_td)

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

        now = ticks_ms()
        prev_out = self._out_mode
        new_out = self._select_out_mode(val)
        self._out_mode = new_out

        if new_out is not None:
            if self._sync_active is not None:
                self._end_resync()
        elif prev_out is not None and self._sync_active is None:
            self._start_resync(prev_out, now)

        if self._sync_active == "low" and self._sync_left is None:
            resync_input = self.sync_low.get("input")
            if resync_input is not None and val >= resync_input:
                self._end_resync()
        elif self._sync_active == "high" and self._sync_left is None:
            resync_input = self.sync_high.get("input")
            if resync_input is not None and val <= resync_input:
                self._end_resync()

        self._apply_value(val)

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
        if self._sync_active is not None:
            res["resync"] = dict(
                mode=self._sync_active,
                left=self._sync_left,
                suspended=self._sync_suspended,
            )
        elif self._out_mode is not None:
            res["out_mode"] = self._out_mode
        elif self.t_on and self.t_off:
            res["t"] = (self.t_on if self.is_on else self.t_off) - ticks_diff(now, self.t_last)
        return res
