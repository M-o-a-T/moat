"""
The ``pump`` unit: the heat pump's state machine and load control (HEAT.md §3.4).

This is the port of the legacy ``run_pump`` without the heating valve,
the pellet burner and source selection. The core decides the heat pump's
power and mode commands and what the ``flow`` unit should do with the
water pump; it never drives the PWM itself.

New compared to the legacy code:

- a dynamic load limit: the load may not exceed an exponential average
  of the recent load plus ``load_limit.margin`` (so the PIDs can't jump
  the compressor to 100 %); raising the temperature goal pushes the
  average up to shorten the ramp;
- a start-up or ice timeout is an abnormal exit (`PumpTimeout`), which
  the adapter turns into an emergency shutdown;
- start permission comes from the selector and the operator override.
"""

from __future__ import annotations

import anyio
import logging
import math
from enum import IntEnum

import asyncclick as click
from pydantic import ConfigDict

from moat.util import pos2val, val2pos
from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)
from moat.link.exceptions import ServiceSupplanted

from .config import EmergencyCfg, UnitCfg, load_config
from .emergency import emergency_shutdown
from .flow import FlowMode, FlowRequest
from .link import Reader, out_path, service_path
from .override import reader as override_reader
from .pid import APID, MonoTime, PIDCfg, PIDState
from .state import State
from .unit import Step, Unit

from typing import Any

_logger = logging.getLogger(__name__)

__all__ = [
    "PumpAbort",
    "PumpCfg",
    "PumpCore",
    "PumpState",
    "PumpTimeout",
    "PumpUnit",
    "Run",
    "TransitionError",
    "cli",
    "next_state",
    "set_force_start",
]


class Run(IntEnum):
    """Heat-pump controller states (as in the legacy code)."""

    off = 0
    """Nothing happens."""
    wait_time = 1
    """Wait for the heat pump to be ready after the last run."""
    wait_flow = 2
    """Wait for any flow."""
    flow = 3
    """Wait for decent flow."""
    wait_power = 4
    """Wait for the heat pump to draw power."""
    temp = 5
    """Wait for ``t_out - t_in`` to exceed ``start.delta``."""
    run = 6
    """Operation."""
    ice = 7
    """The heat pump is de-icing."""
    down = 8
    """Cool down: wait for ``t_out - t_in`` to drop, then off."""


R = Run

_IDLE = (R.off, R.wait_time, R.wait_flow, R.wait_power, R.down)
"""States from which an ``off`` request goes straight to ``off`` (else via ``down``)."""

_HEAT_OFF = {
    R.off: False,
    R.wait_flow: True,
    R.flow: True,
    R.wait_power: True,
    R.temp: True,
    R.run: False,
    R.ice: True,
    R.down: True,
}
"""Whether the heating circuit must stay off in a state (``wait_time``: unchanged)."""


class TransitionError(ValueError):
    """A state change the state machine doesn't allow."""


class PumpTimeout(RuntimeError):
    """A start-up, de-icing or cool-down phase took too long: abnormal exit."""


class PumpAbort(RuntimeError):
    """The adapter saw a critical error or a stale sensor while the heat pump was active."""


def next_state(old: Run | None, new: Run) -> Run:
    """
    Check and resolve a requested state change (the legacy validity rules).

    Args:
        old: The current state, `None` when (re)starting.
        new: The requested state.

    Returns:
        The state to enter; ``off`` requests from active states become ``down``.

    Raises:
        TransitionError: the change is not allowed.
    """
    if old is None or old == new:
        ok = True
    elif new in (R.off, R.ice):
        ok = True
    elif new == old + 1:
        ok = True
    elif new == R.down:
        ok = True  # from anything but off, which is handled below
    elif old == R.ice and new in (R.wait_time, R.wait_flow):
        ok = True
    else:
        ok = False
    if not ok:
        name = None if old is None else old.name
        raise TransitionError(f"Cannot go from {name} to {new.name}")
    if old == R.off and new == R.down:
        # legacy quirk: this also swallows the "defrost" rule of the off state
        return R.off
    if new == R.off and old not in _IDLE:
        # includes restarting (old is None): cool down first
        return R.down
    return new


class _Times(BaseModel):
    start: float = 500
    """Maximum duration of the start-up states (``lim.times.start``)."""
    ice: float = 1000
    """Maximum duration of de-icing (``lim.times.ice``)."""
    stop: float = 150
    """Maximum duration of the cool-down (``lim.times.stop``)."""


class _FlowPoint(BaseModel):
    rate: float
    pwm: float


class _Start(BaseModel):
    delay: float = 450
    """Pause after the last run before starting again (``misc.start.delay``)."""
    init: _FlowPoint = _FlowPoint(rate=6, pwm=0.25)
    """Flow while waiting for flow."""
    power: _FlowPoint = _FlowPoint(rate=15, pwm=0.4)
    """Flow while waiting for power and heat."""
    load: float = 0.1
    """Load while starting (``misc.start.power``)."""
    delta: float = 2
    """``t_out - t_in`` that ends the start-up."""
    min_power: float = 1.2
    """Power draw (kW) that shows the compressor runs (``misc.min_power``)."""
    no_power: float = 30
    """In ``run``, this long without power draw means off."""


class _Adj(BaseModel):
    buffer: float = 3
    """``t_load = t_adj + buffer``."""
    more: float = 2
    """Outflow above ``t_adj``; also the width of the load/limit blend."""
    max: float = 59
    """Maximum ``t_pump`` and ``t_load``."""
    max_max: float = 61
    """Absolute outflow limit (``t_limit`` stays below ``(max + max_max) / 2``)."""
    low_factor: float = 0.4
    """How much a buffer below ``t_low`` raises the limits (``adj.low.factor``)."""
    low_buffer: float = -5
    """``t_buffer = t_low + low_buffer`` (``adj.low.buffer``)."""
    heat_delta: float = 12
    """``t_limit`` is at least ``tb_low + heat_delta`` (``misc.heat.delta``)."""
    pellet_load: float = 3
    """``t_load = t_adj + pellet_load`` while the pellet burner is settled."""
    pellet_max: float = 75
    """Maximum ``t_load`` while the pellet burner is settled."""


class _Low(BaseModel):
    scale: float = 0.015
    """Decay factor of ``scaled_low`` per tick."""
    limit: float = 0.15
    """``scaled_low`` below this ends a run once the buffer is warm."""
    pellet_scale: float = 0.01
    pellet_limit: float = 0.25


class _PelletStart(BaseModel):
    buffer: float = 6
    """Start while the burner is settled if ``tb_heat`` is this far below the heating target."""
    heat_delta: float = 1.5
    """… or if the averaged heating target is this far below."""
    heat_scale: float = 0.01
    """Decay factor of ``avg_heat`` / ``avg_heat_t`` per tick."""
    stop_buffer: float = 0
    """While the burner is hot: off once ``t_cur >= t_nom + stop_buffer`` (OFF 6)."""
    min_load: float = 0.9
    """Don't start while the settled burner runs below this load."""
    max_low: float = 50
    """Don't start while the settled burner keeps ``tb_low`` above this (``lim.start``)."""


class _Stop(BaseModel):
    flow: float = 10
    """Flow while cooling down (``misc.stop.flow``)."""
    delta: float = 3
    """Cool-down ends when ``t_out - t_in`` is below this."""
    defrost_temp: float | None = 7
    """Cool-down doesn't end while the heat pump's water is colder than this.

    (``lim.defrost.temp``)"""
    idle: float = 25
    """… but ends once it is warmer than that and cooler than this (``lim.idle``)."""


class _DeIce(BaseModel):
    flow: float = 18
    pwm: float = 0.5
    min_pwm: float = 0.4


class _LoadLimit(BaseModel):
    """The dynamic load limit (not in the legacy code)."""

    tau: float | None = 600
    """Time constant of the load average, seconds; `None` disables the limit."""
    margin: float = 0.25
    """The load may be at most the average plus this …"""
    floor: float = 0.3
    """… but the limit is never below this."""
    push: float = 0.5
    """When the goal (``t_adj``) rises, raise the average to at least this."""
    push_delta: float = 1
    """… if it rises by at least this many K."""


class PumpCfg(UnitCfg):
    """Configuration of the pump unit. Defaults: the production values."""

    # inputs
    t_in: Path = P("heat.s.pump.temp.in")
    t_out: Path = P("heat.s.pump.temp.out")
    r_flow: Path = P("heat.s.pump.flow")
    m_ice: Path = P("heat.s.pump.de_ice")
    m_power: Path = P("heat.s.pump.power")
    tb_water: Path = P("heat.s.buffer.temp.water")
    tb_heat: Path = P("heat.s.buffer.temp.heat")
    tb_mid: Path = P("heat.s.buffer.temp.mid")
    tb_low: Path = P("heat.s.buffer.temp.return")
    t_heat: Path = P("heat.s.heating.temp.out")
    c_heat: Path = P("heat.s.heat.temp")
    c_water: Path = P("heat.s.water.temp")
    target: Path = out_path("target")
    selector: Path = out_path("selector")
    pellet: Path = out_path("pellet")
    errors: Path = out_path("errors")
    flow_out: Path = out_path("flow")
    passthru: Path = P("app.heat.passthru.state")
    override: Path = P("app.heat.override.wp")
    force_start: Path = P("app.heat.force_start")

    # outputs
    power: Path = P("heat.s.pump.cmd.power")
    mode: Path = P("heat.s.pump.cmd.mode")
    mode_on: int = 3
    mode_off: int = 0
    flow_request: Path = P("app.heat.flow.request")
    cop_out: Path | None = P("home.ass.dyn.sensor.heizung.wp_cop.state")
    feedback_wp: Path | None = P("home.ass.dyn.switch.heizung.wp.state")
    feedback_ice: Path | None = P("home.ass.dyn.binary_sensor.heizung.wp_de_ice.state")

    legacy_state: Path | None = None
    """Also write the run state (a `Run` number) here, as the legacy code did.

    Production used ``heat.s.pump.state``, which is also the heat pump's
    own state (HEAT.md §1), hence off by default."""

    stale: float | None = 900
    """While active, a sensor in `stale_sensors` that has not changed for this
    long (or has no value) stops the unit with an emergency shutdown;
    `None`: never."""
    stale_sensors: list[str] = ["t_in", "t_out", "r_flow", "m_power"]

    min_load: float = 0.05
    """A load below this means power 0 and mode off (``lim.power.min``)."""
    min_run: float = 300
    """OFF 4 only after running this long (``lim.power.time``)."""
    tick: float = 10
    """Step interval while active, seconds."""
    cop_every: float = 600
    """Publish the COP estimate this often, seconds."""

    times: _Times = _Times()
    start: _Start = _Start()
    adj: _Adj = _Adj()
    low: _Low = _Low()
    pellet_start: _PelletStart = _PelletStart()
    stop: _Stop = _Stop()
    de_ice: _DeIce = _DeIce()
    load_limit: _LoadLimit = _LoadLimit()

    load: PIDCfg = PIDCfg()
    """``t_cur`` → load."""
    load_pellet: PIDCfg | None = None
    """Replaces ``load`` while the pellet burner runs (legacy ``adj.pellet.pid.load``)."""
    buffer: PIDCfg = PIDCfg()
    """``tb_low`` → load (limits the load when the buffer bottom gets warm)."""
    limit: PIDCfg = PIDCfg()
    """``t_out`` → load (limits the load when the outflow gets too hot)."""


class PumpPids(BaseModel):
    """The PIDs' persistent state."""

    load: PIDState = PIDState()
    buffer: PIDState = PIDState()
    limit: PIDState = PIDState()


class PumpState(State):
    """Persistent state of the pump unit."""

    model_config = ConfigDict(strict=False)  # "run" is stored as a number

    run: Run = R.off
    t_change: MonoTime = None
    """Start of the current timed phase."""
    t_load: MonoTime = None
    """Last time the heat pump produced heat."""
    t_run: MonoTime = None
    """Start of the current run."""
    scaled_low: float = 1.0
    load_last: float | None = None
    avg_heat: float | None = None
    avg_heat_t: float | None = None
    cop: float = 3.0
    avg_load: float = 0.0
    """The dynamic load limit's average."""
    pids: PumpPids = PumpPids()


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class PumpCore:
    """
    Sans-IO core of the pump unit.

    ``step`` raises `PumpTimeout` when a timed phase takes too long; the
    adapter then runs the emergency shutdown.
    """

    SENSORS = ("t_in", "t_out", "r_flow", "m_power", "tb_water", "tb_heat", "tb_mid", "tb_low")

    def __init__(self, cfg: PumpCfg, state: PumpState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        self.pid_load = APID(cfg.load, state.pids.load, now)
        self.pid_buffer = APID(cfg.buffer, state.pids.buffer, now)
        self.pid_limit = APID(cfg.limit, state.pids.limit, now)
        self._orun: Run | None = None  # None: (re)starting
        self._t_change_max: float | None = None
        self._seq = 0
        self._flow: FlowRequest | None = None
        self._power: float = 0
        self._mode: int = cfg.mode_off
        self._heat_off = False
        self._m_ice = False
        self._was_enabled: bool | None = None
        self._t_no_power: float | None = None
        self._last_cop = -math.inf
        self._t_adj: float | None = None
        self._pellet_gains = False
        self._reason = "init"
        self._t_avg: float | None = None
        self._vals: dict[str, float | None] = {}

    def update_cfg(self, cfg: PumpCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg
        self._pellet_gains = False
        self.pid_load.update_cfg(cfg.load)
        self.pid_buffer.update_cfg(cfg.buffer)
        self.pid_limit.update_cfg(cfg.limit)

    # outputs

    def _load(self, p: float) -> None:
        "set_load: below the minimum, power 0 and mode off"
        if p < self.cfg.min_load:
            self._power, self._mode = 0, self.cfg.mode_off
        else:
            self._power, self._mode = min(p, 1), self.cfg.mode_on

    def _request(self, mode: FlowMode, *, preload: bool = False, **kw: Any) -> None:
        req = FlowRequest(mode=mode, preload=preload, **kw)
        if self._flow is not None:
            old = self._flow.model_copy(update={"seq": 0, "preload": req.preload})
            if old == req.model_copy(update={"seq": 0}):
                return
        self._seq += 1
        req.seq = self._seq
        self._flow = req

    # state changes

    def _enter(self, run: Run, old: Run | None, now: float, t: dict[str, Any]) -> None:
        "entry actions (legacy 'Entering a state')"
        cfg = self.cfg
        st = self.state
        s = cfg.start
        if old is None:
            # restarting
            if st.t_change is not None:
                st.t_change = now
            if run == R.run and st.load_last is not None:
                self._load(st.load_last)
        if old == run:
            return

        if (h := _HEAT_OFF.get(run)) is not None:
            self._heat_off = h

        if run == R.off:
            st.t_change = None
            self._t_change_max = None
            self._request(FlowMode.OFF)
            self._load(0)
        elif run == R.wait_time:
            self._request(FlowMode.OFF)
            self._load(0)
        elif run == R.wait_flow:
            st.t_change = now
            self._timeout(cfg.times.start)
            self._mode = cfg.mode_off
            self._request(FlowMode.FIXED, pwm=s.init.pwm, rate=s.init.rate)
        elif run == R.flow:
            self._timeout(cfg.times.start)
            self._request(FlowMode.RATE, rate=s.init.rate, pwm=s.init.pwm, preload=True)
        elif run == R.wait_power:
            self._timeout(cfg.times.start)
            self._request(FlowMode.RATE, rate=s.power.rate, pwm=s.power.pwm, preload=True)
            self._load(s.load)
        elif run == R.temp:
            self._timeout(cfg.times.start)
            self._request(
                FlowMode.RATE_TEMP,
                rate=s.power.rate,
                temp=t["t_pump"],
                pwm=s.power.pwm,
                preload=True,
            )
        elif run == R.run:
            st.t_change = None
            self._t_change_max = None
            if st.t_run is None:
                st.t_run = now
            if old is not None:
                st.scaled_low = 1.0
                for pid in (self.pid_load, self.pid_buffer, self.pid_limit):
                    pid.pid.reset(t=now)
                    pid.idle(now)
                st.avg_load = self._power
            self._request(FlowMode.TEMP, temp=t["t_pump"], preload=True)
            st.load_last = None
        elif run == R.ice:
            if st.t_change is None:
                st.t_change = now
            self._timeout(cfg.times.ice)
            d = cfg.de_ice
            self._request(
                FlowMode.RATE_TEMP,
                rate=d.flow,
                temp=t["t_pump"],
                pwm=d.pwm,
                min_pwm=d.min_pwm,
                preload=True,
            )
            self._power, self._mode = 0, cfg.mode_off
        elif run == R.down:
            if st.t_change is None:
                st.t_change = now
            self._timeout(cfg.times.stop)
            self._request(FlowMode.RATE_TEMP, rate=cfg.stop.flow, temp=t["t_pump"])
            self._power, self._mode = 0, cfg.mode_off

        if run != R.run:
            st.t_run = None

    def _timeout(self, t: float) -> None:
        if self._t_change_max is None or self._t_change_max < t:
            self._t_change_max = t

    # the step

    def _setpoints(self, v: dict[str, Any], dem: dict[str, Any]) -> dict[str, Any]:
        "the legacy setpoint math"
        a = self.cfg.adj
        t_nom, t_low, t_adj = dem["t_nom"], dem["t_low"], dem["t_adj"]
        t_cur = v["tb_heat"] if dem.get("source", "heat") == "heat" else v["tb_water"]
        f = val2pos(t_nom, t_cur, t_adj, clamp=True) if t_adj != t_nom else 1.0
        max2 = (a.max_max + a.max) / 2
        t_limit = min(max2, max(v["tb_low"] + a.heat_delta, t_adj + a.more))
        if t_cur < t_low:
            t_limit = min(t_limit + (t_low - t_cur) * a.low_factor, max2)
        t_pump = min(a.max, pos2val(t_low, f, t_limit + 0.2 * (t_low - t_limit)))
        return {
            "t_cur": t_cur,
            "t_nom": t_nom,
            "t_low": t_low,
            "t_adj": t_adj,
            "t_set_on": dem["t_set_on"],
            "t_set_off": dem["t_set_off"],
            "t_limit": t_limit,
            "t_pump": t_pump,
            "t_buffer": t_low + a.low_buffer,
        }

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Decide what the heat pump does."""
        cfg = self.cfg
        st = self.state
        outputs: dict[Path, Any] = {}

        v = {k: _num(inputs.get(k)) for k in (*self.SENSORS, "t_heat", "c_heat", "c_water")}
        m_ice = bool(inputs.get("m_ice"))
        target = inputs.get("target") or {}
        dem = target.get("demand") if isinstance(target, dict) else None
        pellet = inputs.get("pellet") or {}
        passthru = inputs.get("passthru")
        missing = [k for k in self.SENSORS if v[k] is None]

        if passthru == "original":
            # the original controller is in charge: stand down, write nothing
            self._orun = None
            st.run = R.off
            outputs[out_path("pump")] = self._out(st.run, "passthru", None)
            return Step(outputs=outputs, save=True)

        if missing or not dem:
            # can't decide anything; don't start, and don't touch a running pump
            self._reason = "missing: " + ",".join(missing or ["demand"])
            outputs[out_path("pump")] = self._out(st.run, self._reason, None)
            return Step(outputs=outputs, wake_in=cfg.tick)

        t = self._setpoints(v, dem)
        enabled = self._enabled(inputs)
        t_pellet_on = pellet.get("t_pellet_on", False)
        pellet_on = bool(pellet.get("pellet_on"))
        self._pellet_pid(pellet_on)

        # PID setpoints (every step, as the legacy code does)
        self.pid_buffer.setpoint(t["t_buffer"])
        self.pid_limit.setpoint(t["t_limit"])

        # averages for the pellet-assisted start decision
        ps = cfg.pellet_start
        if v["t_heat"] is not None:
            st.avg_heat = (
                v["t_heat"]
                if st.avg_heat is None
                else st.avg_heat + (v["t_heat"] - st.avg_heat) * ps.heat_scale
            )
        if (hd := _num(target.get("flow_temp"))) is not None:
            st.avg_heat_t = (
                hd
                if st.avg_heat_t is None
                else st.avg_heat_t + (hd - st.avg_heat_t) * ps.heat_scale
            )

        # goal changes push the load average (dynamic load limit)
        ll = cfg.load_limit
        if self._t_adj is not None and t["t_adj"] >= self._t_adj + ll.push_delta:
            st.avg_load = max(st.avg_load, ll.push)
        if (
            self._t_adj is None
            or t["t_adj"] >= self._t_adj + ll.push_delta
            or t["t_adj"] < self._t_adj
        ):
            self._t_adj = t["t_adj"]

        run = st.run
        force = bool(inputs.get("force_start"))
        save = False
        wake: float | None = None
        vals: dict[str, float | None] = {}

        for _ in range(20):
            # Part 1: state changes
            if self._orun is None or run != self._orun:
                run = next_state(self._orun, run)
                self._enter(run, self._orun, now, t)
                self._orun = run
                st.run = run
                save = True

            if (
                st.t_change is not None
                and self._t_change_max is not None
                and now - st.t_change > self._t_change_max
            ):
                raise PumpTimeout(f"{run.name}: {now - st.t_change:.0f} s")

            # de-icing starts
            if m_ice and not self._m_ice:
                self._m_ice = True
                self._reason = "ice"
                if run != R.ice:
                    run = R.ice
                    continue
            elif not m_ice:
                self._m_ice = False

            # main switch: switching off stops the heat pump once (legacy:
            # only on the edge); a cool-down then runs its course, and
            # "off" doesn't start while disabled
            if not m_ice:
                if not enabled and self._was_enabled is not False:
                    self._was_enabled = False
                    self._reason = self._why_not(inputs)
                    if run != R.off:
                        run = R.off
                        continue
                elif enabled:
                    self._was_enabled = True

            # per-state ticks
            new = self._tick(run, v, t, pellet, t_pellet_on, force, now)
            if new is not None and new != run:
                if run == R.off and new == R.wait_time and force:
                    outputs[cfg.force_start] = None  # consumed
                run = new
                continue
            if run != R.run:
                break

            # RUNNING
            new = self._run(v, t, t_pellet_on, pellet_on, now, vals)
            if new is not None:
                run = new
                continue
            break
        else:
            raise RuntimeError("pump core: state changes don't settle")

        # outputs
        if run in (R.wait_flow, R.flow, R.wait_power, R.temp, R.run, R.ice, R.down):
            wake = cfg.tick
            if run in (R.temp, R.run, R.ice, R.down) and self._flow is not None:
                # the pump PID's setpoint follows t_pump
                self._request(
                    self._flow.mode,
                    **self._flow.model_dump(exclude={"mode", "seq", "preload", "temp"}),
                    temp=t["t_pump"],
                )
        elif run == R.wait_time:
            t_l = st.t_load if st.t_load is not None else now
            wake = max(t_l + cfg.start.delay - now, 0) + 0.001
        if run == R.off and self._m_ice:
            wake = cfg.tick

        outputs[cfg.power] = self._power
        outputs[cfg.mode] = self._mode
        if cfg.legacy_state is not None:
            outputs[cfg.legacy_state] = int(run)
        if self._flow is not None:
            outputs[cfg.flow_request] = self._flow.to_link()
        if cfg.feedback_wp is not None:
            outputs[cfg.feedback_wp] = enabled
        if cfg.feedback_ice is not None:
            outputs[cfg.feedback_ice] = self._m_ice
        if cfg.cop_out is not None and now - self._last_cop >= cfg.cop_every and self._power:
            self._last_cop = now
            outputs[cfg.cop_out] = round(st.cop, 2)
        outputs[out_path("pump")] = self._out(run, self._reason, t, vals)
        for pid in (self.pid_load, self.pid_buffer, self.pid_limit):
            if pid.state.t != now:
                pid.idle(now)
            outputs.update(pid.logs)
            pid.logs.clear()
        return Step(outputs=outputs, wake_in=wake, save=True, save_now=save)

    def _enabled(self, inputs: dict[str, Any]) -> bool:
        ov = inputs.get("override")
        if ov is False:
            return False
        sel = inputs.get("selector")
        if isinstance(sel, dict) and sel.get("wp") is False and ov is not True:
            return False
        err = inputs.get("errors")
        return not (isinstance(err, dict) and err.get("errors"))

    @staticmethod
    def _why_not(inputs: dict[str, Any]) -> str:
        if inputs.get("override") is False:
            return "override"
        err = inputs.get("errors")
        if isinstance(err, dict) and err.get("errors"):
            return "errors"
        return "selector"

    def _pellet_pid(self, pellet_on: bool) -> None:
        "``pid.load`` gains follow the pellet burner (legacy run_set_pellet)"
        cfg = self.cfg
        if cfg.load_pellet is None or pellet_on == self._pellet_gains:
            return
        self._pellet_gains = pellet_on
        self.pid_load.update_cfg(cfg.load_pellet if pellet_on else cfg.load)

    def _tick(
        self,
        run: Run,
        v: dict[str, Any],
        t: dict[str, Any],
        pellet: dict[str, Any],
        t_pellet_on: Any,
        force: bool,
        now: float,
    ) -> Run | None:
        "per-state checks of the non-running states"
        cfg = self.cfg
        st = self.state
        s = cfg.start
        stp = cfg.stop
        t_in, t_out = v["t_in"], v["t_out"]
        if run == R.off:
            ps = cfg.pellet_start
            r: str | None
            if self._was_enabled is False:
                return None  # reason set by the main switch
            if force:
                r = None
            elif t_pellet_on is True:
                if (_num(pellet.get("load")) or 0) < ps.min_load:
                    r = "pellet load low"
                elif v["tb_low"] > ps.max_low:
                    r = "pellet keeps buffer warm"
                elif v["c_water"] is not None and v["tb_water"] < v["c_water"]:
                    r = None
                elif v["c_heat"] is not None and v["tb_heat"] < v["c_heat"] - ps.buffer:
                    r = None
                elif (
                    v["c_heat"] is not None
                    and st.avg_heat_t is not None
                    and st.avg_heat_t > v["c_heat"] - ps.heat_delta
                ):
                    r = "pellet heat ok"
                else:
                    r = "pellet temp"
            elif t["t_cur"] < t["t_set_on"]:
                r = None
            else:
                r = "warm"
            if r is None:
                self._reason = "start"
                return R.wait_time
            self._reason = r
            # The legacy code asks for "down" here when the heat pump's water
            # is below defrost_temp, but its own transition rules turn off ->
            # down into off, so this frost protection never ran (see
            # next_state). Frost protection is a separate unit (moat-n84.29).
            return None
        if run == R.wait_time:
            if st.t_load is None or st.t_load + s.delay < now:
                return R.wait_flow
            return None
        if run == R.wait_flow:
            return R.flow if v["r_flow"] else None
        if run == R.flow:
            return R.wait_power if v["r_flow"] >= s.init.rate * 3 / 4 else None
        if run == R.wait_power:
            return R.temp if v["m_power"] >= s.min_power else None
        if run == R.temp:
            st.t_load = now
            return R.run if t_out - t_in > s.delta else None
        if run == R.run:
            st.t_load = now
            return None
        if run == R.ice:
            if self._m_ice:
                return None
            if v["tb_mid"] > t["t_set_off"]:
                self._reason = "ice done, buffer warm"
                return R.off
            if v["tb_low"] >= t["t_low"]:
                self._reason = "ice done, buffer bottom warm"
                return R.off
            return R.wait_time
        if run == R.down:
            if stp.defrost_temp is not None:
                warm = min(t_out, t_in) > stp.defrost_temp
            else:
                warm = True
            if warm and max(t_out, t_in) < stp.idle:
                return R.off
            if warm and t_out - t_in < stp.delta:
                return R.off
            return None
        return None

    def _run(
        self,
        v: dict[str, Any],
        t: dict[str, Any],
        t_pellet_on: Any,
        pellet_on: bool,
        now: float,
        vals: dict[str, float | None],
    ) -> Run | None:
        "the running heat pump: load control and the OFF rules"
        cfg = self.cfg
        st = self.state
        a = cfg.adj
        t_cur, t_adj = t["t_cur"], t["t_adj"]

        if pellet_on and v["tb_heat"] > t_cur:
            # (never true while heating: then t_cur is tb_heat; legacy quirk)
            if t_cur >= t["t_nom"] + cfg.pellet_start.stop_buffer:
                self._reason = "OFF 6"
                return R.off
            if t_cur >= t_adj:
                self._reason = "OFF 3"
                return R.off

        if v["m_power"] < cfg.start.min_power:
            if self._t_no_power is None:
                self._t_no_power = now
            elif now - self._t_no_power > cfg.start.no_power:
                self._reason = "no power"
                self._t_no_power = None
                return R.off
        else:
            self._t_no_power = None

        if t_pellet_on is True:
            t_load = min(t_adj + a.pellet_load, a.pellet_max)
        else:
            t_load = min(t_adj + a.buffer, a.max)
        self.pid_load.setpoint(t_load)

        l_load = self.pid_load(t_cur, now)
        l_buffer = self.pid_buffer(v["tb_low"], now)
        l_limit = self.pid_limit(v["t_out"], now)
        w = val2pos(t_adj - a.more, t_cur, t_adj)
        l_buf = pos2val(l_limit, w, l_buffer, clamp=True)
        lim = min(l_buf, l_limit, l_load)

        low = cfg.low
        st.scaled_low += (lim - st.scaled_low) * (
            low.pellet_scale if t_pellet_on is True else low.scale
        )

        # dynamic load limit
        ll = cfg.load_limit
        l_max = None
        if ll.tau is not None:
            l_max = max(st.avg_load + ll.margin, ll.floor)
            lim = min(lim, l_max)
        self._load(lim)
        st.load_last = lim
        if ll.tau is not None:
            dt = cfg.tick if self._t_avg is None else now - self._t_avg
            st.avg_load += (self._power - st.avg_load) * (1 - math.exp(-dt / ll.tau))
            self._t_avg = now

        # COP
        if v["m_power"]:
            cop = 1.16 * 60 * v["r_flow"] * (v["t_out"] - v["t_in"]) / 1000 / v["m_power"]
            st.cop += 0.0001 * v["m_power"] * (cop - st.cop)

        vals.update(
            l_load=l_load, l_buffer=l_buffer, l_limit=l_limit, l_buf=l_buf, w=w, l_max=l_max
        )
        self._reason = "run"

        # turn off once the buffer is warm enough
        pellet_low = t_pellet_on is True
        if pellet_low and st.scaled_low < low.pellet_limit:
            self._reason = "OFF SCALE PELLET"
            return R.off
        if t_cur >= t_adj:
            if st.scaled_low < (low.pellet_limit if pellet_low else low.limit):
                self._reason = "OFF SCALED"
                return R.off
            if (
                st.t_run is not None
                and now - st.t_run > cfg.min_run
                and v["tb_mid"] > t["t_set_off"]
            ):
                self._reason = "OFF 4"
                return R.off
            if v["tb_low"] >= t["t_low"]:
                self._reason = "OFF 5"
                return R.off
        return None

    def _out(
        self,
        run: Run,
        reason: str,
        t: dict[str, Any] | None,
        vals: dict[str, float | None] | None = None,
    ) -> dict[str, Any]:
        st = self.state
        res: dict[str, Any] = {
            "run": run.name,
            "active": run not in (R.off, R.down),
            "heat_off": self._heat_off,
            "load": self._power,
            "scaled_low": round(st.scaled_low, 4),
            "cop": round(st.cop, 3),
            "avg_load": round(st.avg_load, 4),
            "reason": reason,
        }
        if t is not None:
            res["t_cur"] = t["t_cur"]
            res["t_pump"] = round(t["t_pump"], 2)
            res["t_limit"] = round(t["t_limit"], 2)
        if vals:
            res.update({k: None if x is None else round(x, 4) for k, x in vals.items()})
        return res


class PumpUnit(Unit[PumpCfg, PumpState]):
    """
    MoaT-Link adapter of the pump unit (HEAT.md §2.5, §2.6).

    Besides running the core, it stops the heat pump with an emergency
    shutdown (`~moat.dev.heat.emergency.emergency_shutdown`) when the unit
    ends abnormally while the heat pump is active: a critical error, a
    stale sensor, a start-up timeout, any other exception, or
    cancellation. It does not when it is supplanted by another process
    (e.g. ``moat dev heat off``), which then owns the shutdown.
    """

    name = "pump"
    cfg_model = PumpCfg
    state_model = PumpState

    emergency: EmergencyCfg = EmergencyCfg()
    """The emergency procedure's settings, loaded when the unit starts."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._seen: dict[str, Any] = {}
        self._changed: dict[str, float] = {}

    async def run(self, *, task_status: Any = anyio.TASK_STATUS_IGNORED) -> None:
        """Run the unit; see :meth:`Unit.run`."""
        # loaded up front: when the unit stops, reading it might not work any more
        self.emergency = await load_config(self.link, "emergency", EmergencyCfg)
        await super().run(task_status=task_status)

    def make_core(self, cfg: PumpCfg, state: PumpState, now: float) -> PumpCore:
        """The core."""
        return PumpCore(cfg, state, now)

    def make_inputs(self, cfg: PumpCfg) -> dict[str, Reader[Any]]:
        """Sensors, peer units, override, force start."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in (
                "t_in",
                "t_out",
                "r_flow",
                "m_ice",
                "m_power",
                "tb_water",
                "tb_heat",
                "tb_mid",
                "tb_low",
                "t_heat",
                "c_heat",
                "c_water",
                "target",
                "selector",
                "pellet",
                "errors",
                "flow_out",
                "passthru",
                "force_start",
            )
        }
        rd["override"] = override_reader(self.link, "wp", cfg.override)
        return rd

    def check(self, inputs: dict[str, Any], now: float) -> None:
        """Stop on a critical error or a stale sensor while the heat pump is active."""
        assert isinstance(self.core, PumpCore)
        cfg = self.core.cfg
        for k in cfg.stale_sensors:
            v = inputs.get(k)
            if k not in self._seen or self._seen[k] != v:
                self._seen[k] = v
                self._changed[k] = now
        if self.store.state.run in (R.off, R.down) or inputs.get("passthru") == "original":
            return
        err = inputs.get("errors")
        if isinstance(err, dict) and err.get("errors") and err.get("severity") == "critical":
            raise PumpAbort(f"errors: {err['errors']}")
        if cfg.stale is not None:
            for k in cfg.stale_sensors:
                if inputs.get(k) is None or now - self._changed[k] > cfg.stale:
                    raise PumpAbort(f"stale sensor: {k}")

    async def _supplanted(self) -> bool:
        "whether another process now owns the pump service"
        try:
            with anyio.fail_after(2):
                ann = await self.link.d_get(service_path(self.service.host, self.name))
        except (KeyError, TimeoutError):
            return False
        return isinstance(ann, dict) and ann.get("id") != self.link.id

    async def abort(self, exc: BaseException) -> None:
        """Emergency shutdown, unless the heat pump is off or we were supplanted."""
        st = self.store.state
        if st.run == R.off:
            return
        if _has(exc, ServiceSupplanted) or (
            _has(exc, anyio.get_cancelled_exc_class()) and await self._supplanted()
        ):
            _logger.warning("Pump service supplanted, not shutting down")
            return
        _logger.error("Pump unit ends in %s: %r; emergency shutdown", st.run.name, exc)
        with anyio.move_on_after(self.emergency.total_timeout + 5):
            res = await emergency_shutdown(
                self.link, self.emergency, from_pump=True, service=self.service
            )
            _logger.warning("Emergency shutdown: %s", res)
        st.run = R.off
        st.t_change = None
        st.t_run = None
        st.load_last = None
        with anyio.move_on_after(5):
            await self.store.save()


def _has(exc: BaseException, cls: type[BaseException]) -> bool:
    "whether ``exc`` is, or is a group containing, a ``cls``"
    if isinstance(exc, BaseExceptionGroup):
        return exc.subgroup(cls) is not None
    return isinstance(exc, cls)


async def set_force_start(link: Any, path: Path = P("app.heat.force_start")) -> None:
    """Ask the pump unit to start once, even if the buffer is warm (legacy ``--force-on``)."""
    await link.d_set(path, True, retain=True)


@click.command(short_help="Run the heat-pump unit.")
@click.option("-f", "--force-on", is_flag=True, help="Start once, even if the buffer is warm.")
@click.pass_obj
async def cli(obj: Any, force_on: bool) -> None:
    """
    Run the ``pump`` unit: the heat pump's state machine and load control.

    It announces the ``heat.pump`` service; ``moat dev heat off`` takes it
    over and shuts the heat pump down.
    """
    from moat.link.client import Link  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        if force_on:
            cfg = await load_config(link, "pump", PumpCfg)
            await set_force_start(link, cfg.force_start)
        await PumpUnit(link).run()
