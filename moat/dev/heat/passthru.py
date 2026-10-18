"""
The ``passthru`` unit: hand the heat pump to its original controller (HEAT.md §2.8).

For maintenance, the Solvis controller (the heat pump's original
controller) can be given direct access to the heat pump: the Modbus shim
and the heat-pump poller then forward its requests (their ``bypass``
watches this unit's state). The switch happens only while the heat pump
is idle, in either direction; a request waits until then.

The unit's state, ``app.heat.passthru.state`` = ``{bypass, switching}``,
is what the other units and the Modbus bypasses act on. It is the unit's
persistent state, so a restart resumes where it was.

If polling the Solvis fails while bypassed, our circulation pump can no
longer follow it, so the bypass ends at once (and the request is reset):
the pump unit then switches the heat pump off and cools it down.
"""

from __future__ import annotations

import logging

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .link import Reader, TreeReader, out_path
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["PassthruCfg", "PassthruCore", "PassthruState", "PassthruUnit", "passthru"]

_logger = logging.getLogger(__name__)

IDLE = "heatpump_idle"
"""``switching``: waiting for the heat pump to be idle."""
SENSORS = "sensors"
"""``switching``: waiting for the heat pump's power (or compressor) reading."""
SOLVIS = "solvis"
"""``switching``: waiting for the Solvis poll to work."""


class PassthruCfg(UnitCfg):
    """Configuration of the passthru unit."""

    # inputs
    request: Path = P("app.heat.passthru.request")
    """Whether the original controller should be in charge. Reset to false by an emergency end."""
    pump: Path = out_path("pump")
    m_power: Path = P("heat.s.pump.power")
    """The heat pump's power draw, kW."""
    compr: Path | None = P("heat.s.pump.compr.speed")
    """The compressor's speed. `None`: not available."""
    errors: list[Path] = []
    """
    Error subtrees (below ``error``) that mean the Solvis can't be polled,
    e.g. its Modbus host's and its poller's service.
    """

    # outputs
    feedback: Path | None = P("app.heat.ha.passthru")
    """``bypass``, copied to Home Assistant as the passthru switch's state."""

    p_idle: float = 1.2
    """The heat pump is idle below this power, kW."""


class PassthruState(State):
    """The unit's state, which is also its published output."""

    bypass: bool = False
    """The original controller is in charge."""
    switching: str | None = None
    """What a requested switch waits for; `None` if there's nothing to do."""


def passthru(value: Any) -> bool:
    """Whether a value of ``app.heat.passthru.state`` says the heat pump is bypassed."""
    return isinstance(value, dict) and value.get("bypass") is True


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


class PassthruCore:
    """
    Sans-IO core of the passthru unit.

    Inputs: ``request``, ``pump`` (the pump unit's output), ``m_power``,
    ``compr``, and ``error_N`` (the configured error subtrees).
    """

    def __init__(self, cfg: PassthruCfg, state: PassthruState, now: float) -> None:  # noqa: ARG002
        self.cfg = cfg
        self.state = state

    def update_cfg(self, cfg: PassthruCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def _wait_for(self, inputs: dict[str, Any], to_bypass: bool) -> str | None:
        """What a switch has to wait for, or `None` if it can happen now."""
        cfg = self.cfg
        if to_bypass and self._failing(inputs):
            return SOLVIS
        power = _num(inputs.get("m_power"))
        compr = _num(inputs.get("compr")) if cfg.compr is not None else 0
        if power is None or compr is None:
            return SENSORS
        if power >= cfg.p_idle or compr > 0:
            return IDLE
        if to_bypass:
            pump = inputs.get("pump")
            if not isinstance(pump, dict) or pump.get("run") != "off":
                return IDLE
        return None

    @staticmethod
    def _failing(inputs: dict[str, Any]) -> bool:
        return any(v for k, v in inputs.items() if k.startswith("error_"))

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        """Switch, if requested and possible."""
        st = self.state
        old = (st.bypass, st.switching)
        out: dict[Path, Any] = {}
        want = inputs.get("request") is True

        if st.bypass and self._failing(inputs):
            _logger.error("Passthru: Solvis poll failed, emergency end")
            st.bypass, st.switching = False, None
            out[self.cfg.request] = False
        elif want == st.bypass:
            st.switching = None
        elif (wait := self._wait_for(inputs, want)) is None:
            _logger.warning("Passthru: %s", "original controller" if want else "ours")
            st.bypass, st.switching = want, None
        else:
            st.switching = wait

        if self.cfg.feedback is not None:
            out[self.cfg.feedback] = st.bypass
        changed = (st.bypass, st.switching) != old
        return Step(outputs=out, save=changed, save_now=changed)


class PassthruUnit(Unit[PassthruCfg, PassthruState]):
    """
    Hand the heat pump to its original controller and back.

    This is the MoaT-Link adapter of the passthru unit.
    """

    name = "passthru"
    cfg_model = PassthruCfg
    state_model = PassthruState

    def make_core(self, cfg: PassthruCfg, state: PassthruState, now: float) -> PassthruCore:
        """The core."""
        return PassthruCore(cfg, state, now)

    def make_inputs(self, cfg: PassthruCfg) -> dict[str, Reader[Any]]:
        """The request, the pump unit's output, power, compressor, error subtrees."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k)) for k in ("request", "pump", "m_power")
        }
        if cfg.compr is not None:
            rd["compr"] = Reader[Any](self.link, cfg.compr)
        for i, p in enumerate(cfg.errors):
            rd[f"error_{i}"] = TreeReader(self.link, P("error") + p)
        return rd
