"""
The ``watchdog`` unit (HEAT.md §3.8).

Covers the case where the pump unit can't run its own emergency shutdown
(hard kill, OOM, host crash): when the pump service disappears while the
heat pump was active, the watchdog runs `emergency_shutdown` for it,
taking over the pump service meanwhile, and records what it did in
``app.heat.watchdog.out``.

The pump service's liveness is MoaT-Link's: its announcement below
``run.host.<host>.heat.pump`` goes away when the unit exits, or when the
link's service monitor sees the client's WILL or its pings stop.

The watchdog never restarts the pump unit. It fires once per pump run:
it is re-armed when the pump unit publishes something new.
"""

from __future__ import annotations

import anyio
import logging

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)
from moat.util.time import time

from .config import EmergencyCfg, UnitCfg, load_config
from .emergency import emergency_shutdown
from .link import Override, Reader, ServiceMonitor, is_up, out_path
from .state import State, state_path
from .unit import Step, Unit

from typing import Any

__all__ = ["WatchdogCfg", "WatchdogCore", "WatchdogState", "WatchdogUnit"]

_logger = logging.getLogger(__name__)

_IDLE = ("off", "down", 0, 8)
"""``run`` values (names, or numbers in the pump's state) of an idle heat pump."""


class WatchdogCfg(UnitCfg):
    """Configuration of the watchdog unit."""

    pump_out: Path = out_path("pump")
    pump_state: Path = state_path("pump")
    passthru: Path = P("app.heat.passthru.state")
    disable: Path = P("app.heat.watchdog.disable")
    """``true`` (or ``{value: true, expires, reason}``) disables the watchdog."""
    t_in: Path = P("heat.s.pump.temp.in")
    t_out: Path = P("heat.s.pump.temp.out")

    grace: float = 5
    """
    Act only after the pump service has been gone this long, seconds. Its
    announcement and its output are separate messages, so they may
    arrive in either order.
    """


class WatchdogState(State):
    """Persistent state of the watchdog: the last intervention, for auditing."""

    last: dict[str, Any] | None = None


def _active(run: Any) -> bool:
    return run is not None and run not in _IDLE


class WatchdogCore:
    """
    Sans-IO core of the watchdog unit.

    Inputs: ``pump`` (the pump service's announcement), ``pump_out``,
    ``pump_state``, ``passthru``, ``disable``, ``t_in``, ``t_out``.

    When the pump service is not up, the pump unit's last output says the
    heat pump is active, and its saved state doesn't say otherwise (after
    its own emergency shutdown it is ``off``), the step asks the adapter to
    shut down (`Step.act`); the adapter reports back with `done`.
    """

    def __init__(self, cfg: WatchdogCfg, state: WatchdogState, now: float) -> None:  # noqa: ARG002
        self.cfg = cfg
        self.state = state
        self._fired_for: Any = None
        self._busy = False
        self._gone_since: float | None = None
        self._changed = False
        self.status = "start"

    def update_cfg(self, cfg: WatchdogCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def done(self, record: dict[str, Any]) -> None:
        """The emergency shutdown has finished; ``record`` describes it."""
        self._busy = False
        self.state.last = record
        self._changed = True

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Decide whether to step in."""
        cfg = self.cfg
        act = None
        out_v = inputs.get("pump_out")
        run = out_v.get("run") if isinstance(out_v, dict) else None
        st_v = inputs.get("pump_state")
        st_run = st_v.get("run") if isinstance(st_v, dict) else None

        wake = None
        up = is_up(inputs.get("pump"))
        if up:
            self._gone_since = None
        elif self._gone_since is None:
            self._gone_since = now

        if self._busy:
            self.status = "shutdown"
        elif inputs.get("disable"):
            self.status = "disabled"
        elif inputs.get("passthru") == "original":
            self.status = "passthru"
        elif up:
            self.status = "watching"
        elif not _active(run) or (st_run is not None and not _active(st_run)):
            self.status = "idle"
        elif out_v == self._fired_for:
            self.status = "done"
        elif now - self._gone_since < cfg.grace:  # ty:ignore[unsupported-operator]
            self.status = "watching"
            wake = self._gone_since + cfg.grace - now  # ty:ignore[unsupported-operator]
        else:
            self.status = "shutdown"
            self._busy = True
            self._fired_for = out_v
            act = f"pump service gone while {run}"
            _logger.error("Watchdog: %s", act)

        save, self._changed = self._changed, False
        out = {"status": self.status, **(self.state.last or {})}
        return Step(
            outputs={out_path("watchdog"): out}, act=act, wake_in=wake, save=save, save_now=save
        )


class WatchdogUnit(Unit[WatchdogCfg, WatchdogState]):
    """
    Shut the heat pump down when its pump unit dies.

    This is the MoaT-Link adapter of the watchdog unit.
    """

    name = "watchdog"
    cfg_model = WatchdogCfg
    state_model = WatchdogState

    def make_core(self, cfg: WatchdogCfg, state: WatchdogState, now: float) -> WatchdogCore:
        """The core."""
        return WatchdogCore(cfg, state, now)

    def make_inputs(self, cfg: WatchdogCfg) -> dict[str, Reader[Any]]:
        """The pump's liveness, output and state; passthru; the disable item; sensors."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in ("pump_out", "pump_state", "passthru", "t_in", "t_out")
        }
        rd["pump"] = ServiceMonitor(self.link, self.service.host, "pump")
        rd["disable"] = Override[Any](self.link, cfg.disable, kind=bool, clear=True)
        return rd

    async def act(self, what: Any) -> None:
        """Run the emergency shutdown and record it."""
        core = self.core
        assert isinstance(core, WatchdogCore)
        t0, m0 = time(), anyio.current_time()
        cfg = await load_config(self.link, "emergency", EmergencyCfg)
        try:
            res = await emergency_shutdown(self.link, cfg, from_pump=False, service=self.service)
        except Exception as exc:
            _logger.exception("Watchdog: emergency shutdown failed")
            res = f"error: {exc!r}"
        delta = None
        try:
            t_in = await self.link.d_get(core.cfg.t_in)
            t_out = await self.link.d_get(core.cfg.t_out)
            delta = round(t_out - t_in, 2)
        except (KeyError, TypeError):
            pass
        rec = {
            "triggered_at": t0,
            "reason": what,
            "result": res,
            "duration": round(anyio.current_time() - m0, 1),
            "exit_delta": delta,
        }
        _logger.warning("Watchdog: %s", rec)
        core.done(rec)
