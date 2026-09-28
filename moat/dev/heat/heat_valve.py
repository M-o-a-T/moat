"""
The ``heat_valve`` unit: the heating circuit (HEAT.md §3.2).

Port of the tail of the legacy ``run_pump`` (``log_hc`` 1…11). The
heating circuit is switched on after it has been "ok" for ``delay``
seconds, and off as soon as it isn't, except while the heat pump runs:
the sudden warm return would overload it (unless the heat pump is routed
to the water buffer, ``m_switch``).

"Ok" means: the pellet burner is on; or the heat pump is in ``temp`` and
its return is too warm for a good start (then the circuit comes on at
once, to get cold water back); or the heat pump is in a settled state,
the current state doesn't keep the circuit off, and the water that would
go to the radiators is warm enough. That temperature blends the heating
buffer and the heat pump's outflow by the circulation pump's PWM.
"""

from __future__ import annotations

import logging

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .link import Reader, out_path
from .pid import MonoTime  # noqa: TC001  # pydantic needs it at runtime
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["HeatValveCfg", "HeatValveCore", "HeatValveState", "HeatValveUnit"]

_logger = logging.getLogger(__name__)

_SETTLED = ("off", "wait_time", "run", "down")
"""Pump states in which the pre-heat test decides."""

REASONS = {
    1: "off",
    2: "keep: pump runs",
    3: "on",
    4: "ok, waiting",
    5: "switched on",
    6: "ok, waiting",
    7: "pump starting",
    8: "pump state",
    9: "too cold",
    10: "cold start",
    11: "cold start, heating disabled",
    12: "too cold",
    13: "pellet burner",
    14: "heating disabled",
    15: "input missing",
}
"""Reasons, by legacy ``log_hc`` number (12… are new)."""


class HeatValveCfg(UnitCfg):
    """Configuration of the heat-valve unit. Defaults: the production values."""

    # inputs
    pump: Path = out_path("pump")
    flow: Path = out_path("flow")
    pellet: Path = out_path("pellet")
    target: Path = out_path("target")
    tb_heat: Path = P("heat.s.buffer.temp.heat")
    tb_low: Path = P("heat.s.buffer.temp.return")
    t_out: Path = P("heat.s.pump.temp.out")
    m_switch: Path = P("heat.s.pump.switchover")
    c_heat: Path = P("heat.s.heat.temp")
    cm_heat: Path = P("app.heat.ha.heat")

    # outputs
    mode: Path | None = P("heat.s.heat.mode.cmd")
    """The Solvis' heating mode (``setting.heat.mode.path``)."""
    mode_on: int = 3
    mode_off: int = 5
    feedback_pump: Path | None = P("app.heat.ha.pump_state")
    """Heating circuit on/off, copied to Home Assistant (``feedback.pump``)."""
    feedback_heat: Path | None = P("app.heat.ha.heat_state")
    """Echo of ``cm_heat`` (``feedback.heat``)."""
    pin: Path | None = None
    """
    Interim replacement of the legacy GPIO heat pin: 1.0 (on) or 0.0 (off),
    for a ``pwm`` daemon output.
    """

    delay: float = 30
    """Switch on after being ok for this long, seconds (``setting.heat.mode.delay``)."""
    low_pwm: float = 0.7
    """At this PWM the pre-heat test uses the outflow only (``adj.low.pwm``)."""
    pre_heat: float = -1
    """Pre-heat threshold relative to ``c_heat`` (``adj.low.pre_heat``)."""
    heat_delta: float = 12
    """In ``temp``, run the circuit if ``tb_low`` plus this exceeds ``t_adj``."""


class HeatValveState(State):
    """Persistent state of the heat-valve unit."""

    heat_ok: bool = False
    """The heating circuit is on."""
    pending: MonoTime = None
    """Ok since, while waiting for ``delay``."""


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _blend(a: float, pos: float, b: float) -> float:
    """``a`` at 0, ``b`` at 1, clamped."""
    pos = min(max(pos, 0.0), 1.0)
    return a + (b - a) * pos


class HeatValveCore:
    """
    Sans-IO core of the heat-valve unit.

    Inputs: ``pump``, ``flow``, ``pellet``, ``target`` (the units'
    published views), ``tb_heat``, ``tb_low``, ``t_out``, ``m_switch``,
    ``c_heat``, ``cm_heat``. If an input that the decision needs is
    missing, the circuit stays as it is.
    """

    def __init__(self, cfg: HeatValveCfg, state: HeatValveState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        if state.pending is not None:
            # restarting: wait again
            state.pending = now

    def update_cfg(self, cfg: HeatValveCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def _ok(self, inputs: dict[str, Any]) -> tuple[bool | None, int]:
        """
        Whether the circuit may run, and why.

        Returns `None` if that can't be decided. ``(True, 10)`` means "at once".
        """
        cfg = self.cfg
        pellet = inputs.get("pellet") or {}
        if pellet.get("t_pellet_on"):
            return True, 13
        pump = inputs.get("pump")
        if not isinstance(pump, dict) or (run := pump.get("run")) is None:
            return None, 15
        cm_heat = inputs.get("cm_heat")
        tb_low = _num(inputs.get("tb_low"))
        t_adj = _num(((inputs.get("target") or {}).get("demand") or {}).get("t_adj"))
        if run == "temp" and tb_low is not None and t_adj is not None:
            if tb_low + cfg.heat_delta > t_adj:
                return (True, 10) if cm_heat else (False, 11)
        if run not in _SETTLED:
            return False, 7
        if pump.get("heat_off"):
            return False, 8
        tb_heat, c_heat = _num(inputs.get("tb_heat")), _num(inputs.get("c_heat"))
        if tb_heat is None or c_heat is None:
            return None, 15
        if inputs.get("m_switch"):
            t = tb_heat
        else:
            t_out = _num(inputs.get("t_out"))
            if t_out is None:
                return None, 15
            pwm = _num((inputs.get("flow") or {}).get("pwm")) or 0
            t = _blend(tb_heat, pwm / cfg.low_pwm, t_out)
        if t < c_heat + cfg.pre_heat:
            return False, 9 if run != "run" or inputs.get("m_switch") else 12
        return True, 0

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Decide whether the heating circuit runs."""
        cfg = self.cfg
        st = self.state
        old = (st.heat_ok, st.pending)
        out: dict[Path, Any] = {}
        wake: float | None = None

        cm_heat = inputs.get("cm_heat")
        if cfg.feedback_heat is not None and cm_heat is not None:
            out[cfg.feedback_heat] = bool(cm_heat)

        ok, hc = self._ok(inputs)
        if ok is None or cm_heat is None:
            hc = 15  # hold
        elif not ok or not cm_heat:
            if not cm_heat:
                hc = 14
            if cm_heat and not st.heat_ok and st.pending is None:
                pass
            elif (
                cm_heat
                and (inputs.get("pump") or {}).get("run") == "run"
                and not inputs.get("m_switch")
            ):
                hc = 2
            else:
                st.heat_ok = False
                st.pending = None
        elif st.heat_ok:
            hc = 3 if hc == 0 else hc
        elif hc == 10:
            st.heat_ok = True
            st.pending = None
        elif st.pending is None:
            st.pending = now
            hc = 4
            wake = cfg.delay
        elif now - st.pending >= cfg.delay:
            st.heat_ok = True
            st.pending = None
            hc = 5
        else:
            hc = 6
            wake = st.pending + cfg.delay - now

        on = st.heat_ok
        if cfg.mode is not None:
            out[cfg.mode] = cfg.mode_on if on else cfg.mode_off
        if cfg.feedback_pump is not None:
            out[cfg.feedback_pump] = on
        if cfg.pin is not None:
            out[cfg.pin] = 1.0 if on else 0.0
        out[out_path("heat_valve")] = {
            "on": on,
            "pending": st.pending is not None,
            "hc": hc,
            "reason": REASONS.get(hc, "ok"),
        }
        changed = (st.heat_ok, st.pending) != old
        return Step(outputs=out, wake_in=wake, save=changed, save_now=st.heat_ok != old[0])


class HeatValveUnit(Unit[HeatValveCfg, HeatValveState]):
    """MoaT-Link adapter of the heat-valve unit."""

    name = "heat_valve"
    cfg_model = HeatValveCfg
    state_model = HeatValveState

    def make_core(self, cfg: HeatValveCfg, state: HeatValveState, now: float) -> HeatValveCore:
        """The core."""
        return HeatValveCore(cfg, state, now)

    def make_inputs(self, cfg: HeatValveCfg) -> dict[str, Reader[Any]]:
        """Peer units, sensors, setpoint, heating switch."""
        return {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in (
                "pump",
                "flow",
                "pellet",
                "target",
                "tb_heat",
                "tb_low",
                "t_out",
                "m_switch",
                "c_heat",
                "cm_heat",
            )
        }
