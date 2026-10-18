"""
The ``flow`` unit: the heat pump's water-pump PWM (HEAT.md §3.3).

The pump unit (and the emergency procedure) say what they want by writing
a `FlowRequest` to ``app.heat.flow.request``; this unit turns it into a
PWM value, using the ``flow`` PID (flow rate → PWM) and the ``pump`` PID
(outflow temperature → PWM).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, ValidationError

from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .frost import FROST_MODE
from .link import Reader, ServiceMonitor, is_up, out_path
from .override import reader as override_reader
from .pid import APID, PIDCfg, PIDState
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["FlowCfg", "FlowCore", "FlowMode", "FlowRequest", "FlowState", "FlowUnit"]


class FlowMode(StrEnum):
    """What a flow request asks for."""

    OFF = "off"
    """PWM 0."""
    FIXED = "fixed"
    """A fixed PWM."""
    RATE = "rate"
    """Hold a flow rate (``flow`` PID)."""
    RATE_TEMP = "rate_temp"
    """The larger of the ``flow`` and ``pump`` PIDs' outputs."""
    TEMP = "temp"
    """Hold the outflow temperature (``pump`` PID)."""
    DRAIN = "drain"
    """Hold a flow rate, at least ``safe_pwm`` (emergency shutdown)."""


class FlowRequest(BaseModel):
    """The content of ``app.heat.flow.request``."""

    model_config = ConfigDict(strict=False)  # "mode" arrives as a string

    mode: FlowMode = FlowMode.OFF
    pwm: float | None = None
    """The PWM in ``fixed`` mode, else the preload value."""
    rate: float | None = None
    """The flow setpoint (``rate``, ``rate_temp``, ``drain``)."""
    temp: float | None = None
    """The outflow temperature setpoint (``rate_temp``, ``temp``)."""
    min_pwm: float | None = None
    """Lower clamp of the result (de-icing)."""
    preload: bool = False
    """On change, preset the PID(s) so that they start at ``pwm``."""
    seq: int = 0
    """Incremented by the writer on every change."""

    def to_link(self) -> dict[str, Any]:
        """The request as written to MoaT-Link (plain types only)."""
        return self.model_dump(mode="json")


class FlowCfg(UnitCfg):
    """Configuration of the flow unit."""

    request: Path = P("app.heat.flow.request")
    """Where the requests come from."""
    override: Path = P("app.heat.override.pwm")
    """Operator override of the PWM (HEAT.md §2.7)."""
    frost: Path | None = out_path("frost")
    """The frost unit's pulses, used while nothing else wants the pump to run."""
    output: Path = P("heat.s.pump.pid")
    """The PWM output (``output.flow.path``)."""
    r_flow: Path = P("heat.s.pump.flow")
    t_out: Path = P("heat.s.pump.temp.out")
    t_in: Path = P("heat.s.pump.temp.in")

    flow: PIDCfg = PIDCfg()
    """The ``flow`` PID: flow rate → PWM."""
    pump: PIDCfg = PIDCfg()
    """The ``pump`` PID: outflow temperature → PWM."""

    max_max: float = 61
    """Above this outflow temperature, ``temp`` mode runs at 1.0 (``adj.max_max``)."""
    tick: float = 10
    """Step interval while a PID is active, in seconds."""
    max_age: float = 300
    """A sensor that has not been updated for this long is stale."""
    freeze: float = 60
    """After a needed sensor goes stale, hold the last PWM for this long, then use ``safe_pwm``."""
    safe_pwm: float = 0.5
    """PWM when the controller can't do better."""
    request_max_age: float = 600
    """A request this old, while the pump unit is not alive, is not trusted any more."""
    stop_delta: float = 3
    """If no request is trusted, run at ``safe_pwm`` until ``t_out - t_in`` is below this."""
    stable_rate: float = 1
    """``stable`` if the flow rate is this close to its setpoint (l/min)."""
    stable_temp: float = 1
    """``stable`` if the outflow temperature is this close to its setpoint (K)."""


class FlowState(State):
    """Persistent state of the flow unit."""

    flow: PIDState = PIDState()
    pump: PIDState = PIDState()
    pwm: float = 0
    """The last PWM written."""
    seq: int | None = None
    """``seq`` of the last request that was applied."""


_NEEDS = {
    FlowMode.RATE: ("r_flow",),
    FlowMode.RATE_TEMP: ("r_flow", "t_out"),
    FlowMode.TEMP: ("t_out",),
    FlowMode.DRAIN: ("r_flow",),
}

_RATE_MODES = (FlowMode.RATE, FlowMode.RATE_TEMP, FlowMode.DRAIN)


class FlowCore:
    """
    Sans-IO core of the flow unit.

    Inputs: ``request``, ``override``, ``r_flow``, ``t_out``, ``t_in``,
    ``frost`` (the frost unit's output: its pulses are used while the PWM
    would otherwise be 0), and ``pump`` (the pump unit's service
    announcement). A sensor is stale when it has not been updated for
    ``max_age`` seconds, according to ``_age`` (the pollers re-send steady
    values); without ``_age``, when its value has not changed for that
    long. A PID whose output is not used only follows the time, so it
    does not integrate over the gap.
    """

    def __init__(self, cfg: FlowCfg, state: FlowState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        self.pid_flow = APID(cfg.flow, state.flow, now)
        self.pid_pump = APID(cfg.pump, state.pump, now)
        self._last: dict[str, Any] = {}
        self._changed: dict[str, float] = {}
        self._req_changed = now
        self._drained = False
        self._ages: dict[str, float | None] = {}

    def update_cfg(self, cfg: FlowCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg
        self.pid_flow.update_cfg(cfg.flow)
        self.pid_pump.update_cfg(cfg.pump)

    def _track(self, inputs: dict[str, Any], now: float) -> None:
        for k in ("r_flow", "t_out", "t_in", "request"):
            v = inputs.get(k)
            if k not in self._last or self._last[k] != v:
                self._last[k] = v
                self._changed[k] = now
                if k == "request":
                    self._req_changed = now

    def _updated(self, name: str, now: float) -> float:
        """When sensor ``name`` was last updated."""
        if (age := self._ages.get(name)) is not None:
            return now - age
        return self._changed[name]

    def _stale_since(self, name: str, now: float) -> float | None:
        """When sensor ``name`` went stale, or `None` if it is fresh."""
        if self._last.get(name) is None:
            return self._changed.get(name, now)
        t = self._updated(name, now) + self.cfg.max_age
        return t if t <= now else None

    @staticmethod
    def _request(raw: Any) -> FlowRequest | None:
        if raw is None:
            return None
        try:
            return FlowRequest.model_validate(raw)
        except ValidationError:
            return None

    def _apply(self, req: FlowRequest, inputs: dict[str, Any], now: float) -> None:
        """Set up the PIDs for a new request."""
        if req.rate is not None:
            self.pid_flow.setpoint(req.rate)
        if req.temp is not None:
            self.pid_pump.setpoint(req.temp)
        if not req.preload:
            return
        pwm = self.state.pwm if req.pwm is None else req.pwm
        if req.mode in _RATE_MODES and req.rate is not None:
            self.pid_flow.move_to(req.rate, pwm, now)
        if req.mode in (FlowMode.TEMP, FlowMode.RATE_TEMP):
            t_out = inputs.get("t_out")
            if t_out is not None:
                self.pid_pump.move_to(t_out, pwm, now)

    def _pid(self, req: FlowRequest, inputs: dict[str, Any], now: float) -> float:
        cfg = self.cfg
        r_flow, t_out = inputs["r_flow"], inputs["t_out"]
        match req.mode:
            case FlowMode.RATE:
                return self.pid_flow(r_flow, now)
            case FlowMode.RATE_TEMP:
                return max(self.pid_flow(r_flow, now), self.pid_pump(t_out, now))
            case FlowMode.TEMP:
                if t_out > cfg.max_max:
                    self.pid_pump.move_to(t_out, 1.0, now)
                    return 1.0
                return self.pid_pump(t_out, now)
            case FlowMode.DRAIN:
                return max(self.pid_flow(r_flow, now), cfg.safe_pwm)
        raise ValueError(req.mode)

    def _stable(self, req: FlowRequest, inputs: dict[str, Any]) -> bool:
        cfg = self.cfg

        def near(value: float | None, target: float | None, tol: float) -> bool:
            return value is not None and target is not None and abs(value - target) <= tol

        ok = True
        if req.mode in _RATE_MODES:
            ok = near(inputs.get("r_flow"), req.rate, cfg.stable_rate)
        if req.mode in (FlowMode.TEMP, FlowMode.RATE_TEMP):
            ok = ok and near(inputs.get("t_out"), req.temp, cfg.stable_temp)
        return ok

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Decide the PWM."""
        cfg = self.cfg
        self._track(inputs, now)
        self._ages = inputs.get("_age") or {}
        wake: float | None = None
        save = False
        stable = False

        req = self._request(inputs.get("request"))
        if req is not None and req.seq != self.state.seq:
            self._apply(req, inputs, now)
            self.state.seq = req.seq
            self._drained = False
            save = True

        ovr = inputs.get("override")
        if ovr is not None:
            mode = "override"
            pwm = min(max(float(ovr), 0.0), 1.0)
        elif req is None or (
            now - self._req_changed > cfg.request_max_age and not is_up(inputs.get("pump"))
        ):
            # no trusted request: keep the water moving while there's heat
            t_in, t_out = inputs.get("t_in"), inputs.get("t_out")
            hot = t_in is None or t_out is None or t_out - t_in >= cfg.stop_delta
            if self._drained or not hot:
                mode, pwm = "idle", 0.0
                self._drained = True
            else:
                mode, pwm = "fallback", cfg.safe_pwm
                wake = cfg.tick
        elif req.mode == FlowMode.OFF:
            mode, pwm, stable = "off", 0.0, True
        elif req.mode == FlowMode.FIXED:
            mode, pwm, stable = "fixed", req.pwm or 0.0, True
        else:
            mode = str(req.mode)
            wake = cfg.tick
            stale = [t for n in _NEEDS[req.mode] if (t := self._stale_since(n, now)) is not None]
            if stale:
                since = min(stale)
                if now - since < cfg.freeze:
                    mode, pwm = "freeze", self.state.pwm
                    wake = min(wake, since + cfg.freeze - now)
                else:
                    mode, pwm = "safe", cfg.safe_pwm
            else:
                pwm = self._pid(req, inputs, now)
                stable = self._stable(req, inputs)
                deadline = min(self._updated(n, now) for n in _NEEDS[req.mode]) + cfg.max_age
                wake = min(wake, max(deadline - now, 0))
                save = True
            if req.min_pwm is not None:
                pwm = max(pwm, req.min_pwm)

        if ovr is None and pwm == 0:
            # nothing else wants the pump to run: frost-protection pulses
            fp = (inputs.get("frost") or {}).get("pulse")
            if isinstance(fp, (int, float)) and not isinstance(fp, bool) and fp > 0:
                mode, pwm = FROST_MODE, min(float(fp), 1.0)

        if pwm != self.state.pwm:
            self.state.pwm = pwm
            save = True
        outputs: dict[Path, Any] = {
            cfg.output: pwm,
            out_path("flow"): {
                "pwm": pwm,
                "mode": mode,
                "stable": stable,
                "request_seq": None if req is None else req.seq,
            },
        }
        for pid in (self.pid_flow, self.pid_pump):
            if pid.state.t != now:
                pid.idle(now)
            outputs.update(pid.logs)
            pid.logs.clear()
        return Step(outputs=outputs, wake_in=wake, save=save)


class FlowUnit(Unit[FlowCfg, FlowState]):
    """
    Drive the heat pump's water pump (PWM) as requested.

    This is the MoaT-Link adapter of the flow unit.
    """

    name = "flow"
    cfg_model = FlowCfg
    state_model = FlowState

    def make_core(self, cfg: FlowCfg, state: FlowState, now: float) -> FlowCore:
        """The core."""
        return FlowCore(cfg, state, now)

    def make_inputs(self, cfg: FlowCfg) -> dict[str, Reader[Any]]:
        """Request, override, sensors, and whether the pump unit is alive."""
        return {
            "request": Reader[Any](self.link, cfg.request),
            "override": override_reader(self.link, "pwm", cfg.override),
            "r_flow": Reader[float](self.link, cfg.r_flow, max_age=cfg.max_age),
            "t_out": Reader[float](self.link, cfg.t_out, max_age=cfg.max_age),
            "t_in": Reader[float](self.link, cfg.t_in, max_age=cfg.max_age),
            **({} if cfg.frost is None else {"frost": Reader[Any](self.link, cfg.frost)}),
            "pump": ServiceMonitor(self.link, self.service.host, "pump"),
        }
