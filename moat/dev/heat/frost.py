"""
The ``frost`` unit: frost protection of the heat-pump loop.

Port of the standalone ``wp.py`` task. The heat pump's water loop runs
outside; while the heat pump is idle, its water cools down. When the
colder of ``t_in`` and ``t_out`` drops below ``t_start``, the unit opens
the loop valve and pulses the circulation pump (``pulse`` PWM for
``t_pulse`` seconds, then a pause of ``t_wait`` seconds), pulling warm buffer water
through the loop, until that temperature is back at ``t_stop`` or the
valve is closed by someone else. The valve stays open between pulses, as
some water keeps moving through it.

The unit also owns the loop valve otherwise: it is open while anyone
else runs the circulation pump (``flow.out.pwm > 0``), and closed when
that stops, unless a frost cycle is running. If someone else starts the
pump during a cycle, the cycle ends and the valve stays with them.

The pulses are not written to the PWM output: this unit publishes them
in ``app.heat.frost.out`` and the flow unit uses them while nobody asks
it for anything else.
"""

from __future__ import annotations

import logging

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .link import Reader, out_path
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["FROST_MODE", "FrostCfg", "FrostCore", "FrostState", "FrostUnit"]

_logger = logging.getLogger(__name__)

FROST_MODE = "frost"
"""The flow unit's ``mode`` while it outputs a frost pulse."""


class FrostCfg(UnitCfg):
    """Configuration of the frost unit. Defaults: those of ``wp.py``."""

    # inputs
    t_in: Path = P("heat.s.pump.temp.in")
    t_out: Path = P("heat.s.pump.temp.out")
    flow: Path = out_path("flow")
    valve_state: Path | None = P("app.heat.ha.valve.state")
    """The valve's feedback; closing it ends a frost cycle. `None`: not available."""

    # outputs
    valve: Path = P("app.heat.ha.valve.cmd")
    """The heat-pump loop valve."""

    t_start: float = 8
    """Start a cycle when the loop gets colder than this, °C."""
    t_stop: float = 10
    """End it when the loop is at least this warm again, °C."""
    pulse: float = 1 / 16
    """PWM of a pulse (above the pump's dead zone)."""
    t_pulse: float = 5
    """Length of a pulse, seconds."""
    t_wait: float = 60
    """Pause after a pulse, seconds."""


class FrostState(State):
    """The frost unit keeps no persistent state: a restart re-checks the temperature."""


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


class FrostCore:
    """
    Sans-IO core of the frost unit.

    Inputs: ``t_in``, ``t_out``, ``flow`` (the flow unit's output) and
    ``valve_state``.
    """

    def __init__(self, cfg: FrostCfg, state: FrostState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        self._t_min: float | None = None
        self.active = False
        """A frost cycle runs."""
        self._pulse_at = now
        """Start of the current or next pulse."""
        self._ext = False
        """Someone else runs the circulation pump."""
        self._valve_seen = False
        """The valve has reported open during this cycle."""
        self.reason = "start"

    def update_cfg(self, cfg: FrostCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def _end(self, reason: str) -> None:
        _logger.info("Frost cycle ends: %s", reason)
        self.active = False
        self.reason = reason

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Run the frost cycle and set the valve."""
        cfg = self.cfg
        wake: float | None = None

        flow = inputs.get("flow") or {}
        pwm = _num(flow.get("pwm")) or 0
        self._ext = pwm > 0 and flow.get("mode") != FROST_MODE

        t_in, t_out = _num(inputs.get("t_in")), _num(inputs.get("t_out"))
        if t_in is not None and t_out is not None:
            t = min(t_in, t_out)
            prev, self._t_min = self._t_min, t
            if (
                t < cfg.t_start
                and (prev is None or prev >= cfg.t_start)
                and not self.active
                and not self._ext
            ):
                _logger.info("Frost cycle starts: %.1f", t)
                self.active = True
                self._pulse_at = now
                self._valve_seen = False
                self.reason = "cold"

        pulse = 0.0
        if self.active:
            vs = inputs.get("valve_state")
            if vs:
                self._valve_seen = True
            if self._ext:
                self._end("pump runs")
            elif self._t_min is not None and self._t_min >= cfg.t_stop:
                self._end("warm")
            elif self._valve_seen and vs is False:
                self._end("valve closed")
            else:
                period = cfg.t_pulse + cfg.t_wait
                while now >= self._pulse_at + period:
                    self._pulse_at += period
                if now < self._pulse_at + cfg.t_pulse:
                    pulse = cfg.pulse
                    wake = self._pulse_at + cfg.t_pulse - now
                else:
                    wake = self._pulse_at + period - now

        out: dict[Path, Any] = {
            cfg.valve: self.active or self._ext,
            out_path("frost"): {
                "active": self.active,
                "pulse": pulse,
                "t_min": self._t_min,
                "reason": self.reason,
            },
        }
        return Step(outputs=out, wake_in=wake)


class FrostUnit(Unit[FrostCfg, FrostState]):
    """MoaT-Link adapter of the frost unit."""

    name = "frost"
    cfg_model = FrostCfg
    state_model = FrostState

    def make_core(self, cfg: FrostCfg, state: FrostState, now: float) -> FrostCore:
        """The core."""
        return FrostCore(cfg, state, now)

    def make_inputs(self, cfg: FrostCfg) -> dict[str, Reader[Any]]:
        """Loop temperatures, the flow unit's output, the valve's feedback."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k)) for k in ("t_in", "t_out", "flow")
        }
        if cfg.valve_state is not None:
            rd["valve_state"] = Reader[Any](self.link, cfg.valve_state)
        return rd
