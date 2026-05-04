"""
Control wrapper for a `PWM` part.

The `Control` part wraps a PWM and adds the sync/resync logic, dead
zones, optional PID I-term locking, and value scaling (input in
[0..base]).  Its ``cmd_w`` returns the [0..1] value sent to the wrapped
PWM.
"""

from __future__ import annotations

from moat.lib.micro import (
    Event,
    L,
    TaskGroup,
    every_ms,
    idle,
    retry_ms,
    ticks_diff,
    ticks_ms,
)
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.lib.rpc import Msg, SubMsgSender

    from collections.abc import Mapping


class Control(BaseCmd):
    """
    Sync/resync state machine for slow PWM-style outputs.

    Translates an input in ``[0..base]`` into an output in ``[0..1]``,
    handling dead zones, resync clamping, and optional PID I-term locking
    while the output is forced.  Forwarding the resulting value to a
    ``PWM`` (or any other consumer) is the caller's responsibility.

    Parameters:
        base(float): the maximum value for the input ratio.
        init(float): initial value (defaults to 0)
        sync_low(dict): Resync settings for low transitions. The
            ``sync_low.threshold`` acts as the minimum value; output is off
            below it.
        sync_high(dict): Resync settings for high transitions. The
            ``sync_high.threshold`` acts as the maximum value; output is on
            above it.
        sync_path(Path): Path to read periodically while resync is active.
        sync_invert(bool): Invert sync_path comparison.
        sync_pid(Path): Path to a PID part; while resync is forcing the
            output, the PID's I term is locked.

    ``cmd_w`` returns the resulting ``[0..1]`` value.  The same value is
    available via ``cmd_r`` and as ``out`` in ``cmd_s``; it is updated
    asynchronously when the resync timer expires or when the resync
    suspension state toggles.

    Resync uses ``sync_low``/``sync_high`` to clamp the input when
    transitioning back into range. When the input crosses above
    ``sync_low.threshold``, the effective input is set to at least
    ``sync_low.input`` and resync begins. When the input drops below
    ``sync_high.threshold``, it is clamped to at most ``sync_high.input``.
    Resync ends when ``t_sync`` expires, when the input returns out of
    range, or when ``t_sync`` is unset and the input passes the resync
    input. While resync is active, ``sync_path`` can suspend resync based
    on ``sync_low.bound``/``sync_high.bound``.
    """

    value: float = 0.0  # in [0..base]
    init: float = 0.0
    base: float = 1000
    force: float | None = None
    out: float = 0.0  # last computed [0..1] output
    out_evt: Event  # set by _apply_value whenever ``out`` changes

    sync_low: dict
    sync_high: dict
    sync_invert: bool = False
    sync_path: SubMsgSender | None = None
    _sync_pid: SubMsgSender | None = None

    # Sync/resync state tracking
    _out_mode: str | None = None
    _sync_active: str | None = None
    _sync_left: int | None = None
    _sync_suspended: bool = False
    _sync_check_ms: int | None = None
    _resync_scope = None  # anyio.CancelScope | None — cancel scope of resync task
    _pid_lock_scope = None  # anyio.CancelScope | None — cancel scope of PID lock task
    _tg = None  # ty: TaskGroup | None — set in task()

    _d_threshold = dict(
        _d="describes behavior at min/max boundaries",
        bound="float:suspend resync if @sync_path exceeds this",
        t_sync="int:max resync time (s, optional)",
        t_check="int:interval for value check (s, default 10)",
        threshold="float:threshold to start resync, off below/on above",
        input="float:input during resync, in [0..base]",
        lock="bool:block PID I increase/decrease while resync forces output",
    )

    doc = dict(
        _c=dict(
            _d="Slow PWM control state machine",
            base="float:input range 0...(1000)",
            init="float:initial value",
            sync_low=_d_threshold,
            sync_high=_d_threshold,
            sync_path="path:value to check",
            sync_invert="bool:checked value inverted WRT input?",
            sync_pid="path:PID controller (blocks I during sync)",
        )
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        self._load()
        self.out_evt = Event()

    def _load_sync(self, name: str) -> dict:
        cfg = self.cfg.get(name) or {}
        return dict(
            threshold=cfg.get("threshold"),
            input=cfg.get("input"),
            t_sync=cfg.get("t_sync"),
            t_check=cfg.get("t_check", 10),
            bound=cfg.get("bound"),
            lock=cfg.get("lock", False),
        )

    def _load(self):
        cfg = self.cfg
        self.base = cfg.get("base", self.base)
        self.init = cfg.get("init", self.init)
        self.sync_invert = cfg.get("sync_invert", False)
        self.sync_low = self._load_sync("sync_low")
        self.sync_high = self._load_sync("sync_high")

    def _load_sync_path(self):
        # Calling `await self.sync_path()` returns the float to check
        # cfg.sync_low.bound or cfg.sync_high.bound against.
        # Must be called after the command is attached (root is available).
        if "sync_path" not in self.cfg:
            self.sync_path = None
            return
        sp = self.root.sub_at(self.cfg.sync_path)
        if not hasattr(sp, "cmd"):
            raise TypeError(sp)
        self.sync_path = sp

    def _load_sync_pid(self):
        # Stores a sender to the PID's "lock" sub-command.
        # Must be called after the command is attached (root is available).
        if "sync_pid" not in self.cfg:
            self._sync_pid = None
            return
        self._sync_pid = self.root.sub_at(self.cfg.sync_pid / "lock")

    async def reload(self):
        "reload from config"
        self._load()
        self._load_sync_path()
        self._load_sync_pid()
        await super().reload()

    async def setup(self):  # noqa:D102
        await super().setup()
        self._load_sync_path()
        self._load_sync_pid()
        self.value = self.init

    async def task(self):  # noqa:D102
        async with TaskGroup() as self._tg:
            if L:
                self.set_ready()
            self._apply_value(self.value)
            await idle()

    @property
    def val(self) -> float:
        """The current effective value (forced or normal)."""
        if self.force is not None:
            return self.force
        return self.value

    def _sync_cfg(self, mode: str) -> dict:
        return self.sync_low if mode == "low" else self.sync_high

    def _start_resync(self, mode: str) -> None:
        cfg = self._sync_cfg(mode)
        if cfg.get("input") is None:
            return
        if self._resync_scope is not None:
            self._resync_scope.cancel()
            self._resync_scope = None
        self._sync_active = mode
        t_sync = cfg.get("t_sync")
        self._sync_left = None if t_sync is None else int(t_sync * 1000)
        self._sync_suspended = False
        if self.sync_path is not None and cfg.get("bound") is not None:
            t_check = cfg.get("t_check", 10)
            self._sync_check_ms = int(t_check * 1000)
        else:
            self._sync_check_ms = None

    def _end_resync(self) -> None:
        if self._resync_scope is not None:
            self._resync_scope.cancel()
            self._resync_scope = None
        self._sync_active = None
        self._sync_left = None
        self._sync_suspended = False
        self._sync_check_ms = None
        self._end_pid_lock()

    def _end_pid_lock(self) -> None:
        if self._pid_lock_scope is not None:
            self._pid_lock_scope.cancel()
            self._pid_lock_scope = None

    async def _start_pid_lock(self, mode: str) -> None:
        if self._pid_lock_scope is not None:
            return
        if self._sync_pid is None or self._tg is None:
            return
        up = mode == "low"  # True blocks I increase; False blocks I decrease
        sync_pid = self._sync_pid

        async def _do_lock() -> None:
            async with sync_pid.stream_out(up=up):
                await idle()
            self._pid_lock_scope = None

        self._pid_lock_scope = await self._tg.spawn(_do_lock, _name="PIDLock")

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

    def _apply_value(self, val: float) -> float:
        """
        Compute the effective [0..1] output, store it in ``self.out``, and
        wake up any waiters on ``self.out_evt``.
        """
        if self._out_mode == "low":
            eff = 0.0
        elif self._out_mode == "high":
            eff = 1.0
        else:
            eff_val = val
            if self._sync_active is not None and not self._sync_suspended:
                eff_val = self._sync_value(val)
            eff = eff_val / self.base

        self.out = eff
        self.out_evt.set()
        self.out_evt = Event()
        return eff

    async def _resync_countdown(self, t_ms: int) -> None:
        """
        Countdown task that ends the active resync after ``t_ms`` of
        non-suspended time.
        """
        t_check = self._sync_check_ms
        # Choose interval and optional path call.
        interval = t_check if t_check is not None else t_ms
        p = self.sync_path if t_check is not None else None

        # Start PID lock if configured: output is forced (not suspended) from the start.
        mode = self._sync_active
        should_lock = (
            p is not None
            and mode is not None
            and self._sync_pid is not None
            and self._sync_cfg(mode).get("lock")
        )
        if should_lock and not self._sync_suspended:
            await self._start_pid_lock(cast(str, mode))

        remaining = t_ms
        last = ticks_ms()
        async for _value in every_ms(interval):
            now = ticks_ms()
            dt = ticks_diff(now, last)
            last = now

            if p is not None and self._sync_active is not None:
                cfg = self._sync_cfg(self._sync_active)
                bound = cfg.get("bound")
                if bound is not None:
                    sync_value = await retry_ms(0, 10, p, _exc=ValueError)
                    assert sync_value is not None
                    prev = self._sync_suspended
                    cond = (
                        sync_value < bound
                        if self.sync_invert == (self._sync_active == "low")
                        else sync_value > bound
                    )
                    self._sync_suspended = cond
                    if prev != cond:
                        self._apply_value(self.val)
                        if should_lock:
                            if cond:  # became suspended → output no longer forced
                                self._end_pid_lock()
                            else:  # became not-suspended → output forced again
                                await self._start_pid_lock(self._sync_active)

            if not self._sync_suspended:
                remaining -= dt
            if remaining <= 0:
                break

        # Clear scope before _end_resync so it does not try to cancel itself.
        self._resync_scope = None
        self._end_resync()
        self._apply_value(self.val)

    async def _maybe_start_resync(self) -> None:
        """
        Spawn a resync countdown task if resync is active with a timer
        and no task is already running.
        """
        if (
            self._sync_active is not None
            and self._sync_left is not None
            and self._resync_scope is None
            and self._tg is not None
        ):
            sync_left = self._sync_left

            async def _run_resync() -> None:
                await self._resync_countdown(sync_left)

            self._resync_scope = await self._tg.spawn(_run_resync, _name="Resync")

    async def _set_value(self, val: float | None, force: bool) -> float:
        """
        Update the input value, run the resync state machine, and compute
        the resulting [0..1] output value.
        """
        if val is None:
            if not force:
                raise ValueError(val)
            self.force = None
            val = self.value
        else:
            if val < 0 or val > self.base:
                raise ValueError(val, self.base)
            if force:
                self.force = val
            else:
                self.value = val

        prev_out = self._out_mode
        new_out = self._select_out_mode(val)
        self._out_mode = new_out

        if new_out is not None:
            if self._sync_active is not None:
                self._end_resync()
        elif prev_out is not None and self._sync_active is None:
            self._start_resync(prev_out)

        # Without a t_sync timer, resync ends as soon as the value passes
        # the resync input clamp level.
        if self._sync_active == "low" and self._sync_left is None:
            resync_input = self.sync_low.get("input")
            if resync_input is not None and val >= resync_input:
                self._end_resync()
        elif self._sync_active == "high" and self._sync_left is None:
            resync_input = self.sync_high.get("input")
            if resync_input is not None and val <= resync_input:
                self._end_resync()

        await self._maybe_start_resync()
        return self._apply_value(val)

    doc_w = dict(
        _d="change",
        _0="float|None:new value [0..base]",
        f="bool:forced value",
        _r="float:resulting output [0..1]",
        _i=dict(_0="float:new value [0..base]"),
    )

    async def stream_w(self, msg: Msg):
        "change value"
        force = msg.get("f", False)

        if msg.can_stream:
            async with msg.stream_in() as md:
                async for m in md:
                    await self._set_value(m[0], force)
        else:
            return await self._set_value(msg[0], force)

    doc_r = dict(_d="wait for output change", _r="float:next [0..1] output")

    async def stream_r(self, msg: Msg) -> None:
        "read value"
        if msg.can_stream:
            async with msg.stream_out() as md:
                while True:
                    await self.out_evt.wait()
                    await md.send(self.out)
        else:
            await self.out_evt.wait()
            await msg.result(self.out)

    doc_s = dict(
        _d="read state",
        _r=dict(
            val="float:current input value",
            out="float:current [0..1] output",
            force="float:current forced input (if any)",
            resync="dict:resync state",
            out_mode="str:'low' or 'high' if forcing the output",
        ),
    )

    async def cmd_s(self) -> Mapping:
        "Returns the current state."
        res: dict[str, object] = dict(val=self.value, out=self.out)
        if self.force is not None:
            res["force"] = self.force
        if self._sync_active is not None:
            res["resync"] = dict(
                mode=self._sync_active,
                suspended=self._sync_suspended,
            )
        elif self._out_mode is not None:
            res["out_mode"] = self._out_mode
        return res
