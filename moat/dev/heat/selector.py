"""
The ``selector`` unit: which heat sources run (HEAT.md §3.6).

Replaces the legacy ``run_temp_thresh``, which only switched the pellet
burner's request flag. The selector names a primary source and tells
each source whether it may run:

- ``steady``: only the primary runs.
- ``wp_to_pellet``: the burner is requested; the heat pump keeps running
  until the burner is hot enough to take over (``pellet.out.hot``).
- ``pellet_to_wp``: the heat pump is released; the burner keeps running
  until the heat pump has been in ``run`` for a while, or has stayed
  idle without trouble (it isn't needed yet).

If a source fails (heat-pump errors; burner fault codes, or it doesn't
start or get hot in time), the selector falls back to the other one and
won't choose the failed one again on its own for a while. Operator
overrides force a source on or off; a source forced off is never used
as a fallback.

The primary choice is the legacy one: the burner takes over when it is
cold outside (now and forecast) and the buffer is below ``t_nom``; the
heat pump takes over again when it's warmer outside and the buffer is
fine. A candidate change must hold for ``debounce`` seconds. Missing
inputs latch the current choice.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .link import Reader, out_path
from .override import reader as override_reader
from .pid import MonoTime  # noqa: TC001  # pydantic needs it at runtime
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["Phase", "SelectorCfg", "SelectorCore", "SelectorState", "SelectorUnit"]

_logger = logging.getLogger(__name__)

WP = "wp"
PELLET = "pellet"


class Phase(StrEnum):
    """Handover phase."""

    STEADY = "steady"
    WP_TO_PELLET = "wp_to_pellet"
    PELLET_TO_WP = "pellet_to_wp"


class SelectorCfg(UnitCfg):
    """Configuration of the selector unit. Defaults: the production values."""

    # inputs
    m_air: Path = P("home.ass.dyn.sensor.temp.garten_kompost_schatten.state")
    """Current outside temperature (``sensor.temp.current``)."""
    m_air_pred: Path = P("temp.min.forecast:6")
    """Forecast minimum (``sensor.temp.predict``)."""
    pellet_state: Path = P("heat.s.pellets.state")
    """The burner's KWB state code (``sensor.pellet.state``)."""
    tb_water: Path = P("heat.s.buffer.temp.water")
    tb_heat: Path = P("heat.s.buffer.temp.heat")
    tb_low: Path = P("heat.s.buffer.temp.return")
    cm_heat: Path = P("home.ass.dyn.switch.heizung.main.cmd")
    target: Path = out_path("target")
    pump: Path = out_path("pump")
    pellet: Path = out_path("pellet")
    errors: Path = out_path("errors")
    override_wp: Path = P("app.heat.override.wp")
    override_pellet: Path = P("app.heat.override.pellet")

    # outputs
    wanted: Path = P("heat.s.pellets.power.cmd.auto")
    """The burner's request flag (``cmd.pellet.wanted``)."""
    feedback_pellet: Path | None = None
    """Echo of the request flag (``feedback.pellet``)."""

    # primary choice (misc.pellet)
    current: float = 1
    """The burner takes over below this outside temperature …"""
    predict: float = 0.5
    """… if the lower of current and forecast is below this (minus ``hyst``)."""
    hyst: float = 0.15
    avg_off: float = -1
    """The heat pump takes over only if ``target.out.t_ext`` is above this."""
    idle_codes: list[int] = [0, 30, 31, 32]
    """The burner is requested only while it reports one of these codes."""
    debounce: float = 120
    """A primary change must be called for this long, seconds."""

    # handover and fallback
    stable: float = 600
    """``pellet_to_wp``: release the burner after the heat pump ran this long, seconds."""
    idle_release: float = 1800
    """``pellet_to_wp``: … or after the heat pump stayed idle without errors this long."""
    start_timeout: float = 1800
    """The burner has failed if it isn't running this long after being requested."""
    hot_timeout: float = 3600
    """``wp_to_pellet``: the burner has failed if it isn't hot this long after being requested."""
    fail_codes: list[int] = []
    """Burner state codes that mean it has failed."""
    retry: float = 7200
    """Don't choose a failed source again on our own for this long, seconds."""
    tick: float = 10
    """Step interval, seconds."""


class SelectorState(State):
    """Persistent state of the selector unit."""

    primary: str | None = WP
    phase: str = Phase.STEADY.value
    """A `Phase` (stored as a plain string)."""
    since: MonoTime = None
    """Start of the current phase."""
    failed: dict[str, MonoTime] = {}
    """Sources that failed, and when."""


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _other(src: str) -> str:
    return PELLET if src == WP else WP


class SelectorCore:
    """
    Sans-IO core of the selector unit.

    Inputs: ``m_air``, ``m_air_pred``, ``pellet_state``, ``tb_water``,
    ``tb_heat``, ``tb_low``, ``cm_heat``, the ``target``, ``pump``,
    ``pellet`` and ``errors`` units' outputs, ``override_wp`` and
    ``override_pellet``.
    """

    def __init__(self, cfg: SelectorCfg, state: SelectorState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        # restarting: timers start again
        state.since = now
        state.failed = dict.fromkeys(state.failed, now)
        self._cand: str | None = None
        self._cand_since = now
        self._run_since: float | None = None
        self._idle_since: float | None = None
        self._p_off_since: float | None = None
        self.reason = "start"

    def update_cfg(self, cfg: SelectorCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    # the legacy primary choice

    def _auto(self, inputs: dict[str, Any]) -> str | None:
        """The primary that the temperatures call for; `None`: no change."""
        cfg = self.cfg
        air, pred = _num(inputs.get("m_air")), _num(inputs.get("m_air_pred"))
        tb_water, tb_heat = _num(inputs.get("tb_water")), _num(inputs.get("tb_heat"))
        dem = (inputs.get("target") or {}).get("demand") or {}
        t_nom, t_low = _num(dem.get("t_nom")), _num(dem.get("t_low"))
        if air is None or pred is None or tb_water is None or tb_heat is None or t_nom is None:
            return None
        pred = min(air, pred)
        if self.state.primary != PELLET:
            buf = min(tb_water, tb_heat) if inputs.get("cm_heat") else tb_water
            if (
                inputs.get("pellet_state") in cfg.idle_codes
                and air < cfg.current
                and pred < cfg.predict - cfg.hyst
                and buf < t_nom
            ):
                return PELLET
            return None
        t_ext = _num((inputs.get("target") or {}).get("t_ext"))
        t_on = (inputs.get("pellet") or {}).get("t_pellet_on")
        if (
            air > cfg.current
            and pred > cfg.predict + cfg.hyst
            and t_low is not None
            and tb_heat > t_low
            and t_ext is not None
            and t_ext > cfg.avg_off
            and isinstance(t_on, bool)  # not while it's starting
        ):
            return WP
        return None

    def _debounced(self, want: str | None, now: float) -> str | None:
        if want is None:
            self._cand = None
            return None
        if want != self._cand:
            self._cand = want
            self._cand_since = now
        if now - self._cand_since >= self.cfg.debounce:
            self._cand = None
            return want
        return None

    # health

    @staticmethod
    def _wp_bad(inputs: dict[str, Any]) -> str | None:
        err = inputs.get("errors")
        if isinstance(err, dict) and err.get("errors"):
            return "heat pump errors"
        return None

    def _pellet_bad(self, inputs: dict[str, Any], watch: bool, now: float) -> str | None:
        """
        Whether the burner has failed.

        Args:
            watch: The burner should be running now.
        """
        cfg = self.cfg
        code = inputs.get("pellet_state")
        if code in cfg.fail_codes:
            return f"burner fault {code}"
        mode = (inputs.get("pellet") or {}).get("mode")
        if watch and mode != "running":
            if self._p_off_since is None:
                self._p_off_since = now
            elif now - self._p_off_since > cfg.start_timeout:
                return "burner doesn't run"
        else:
            self._p_off_since = None
        return None

    def _blocked(self, src: str, now: float) -> bool:
        t = self.state.failed.get(src)
        return t is not None and now - t < self.cfg.retry

    # the state machine

    def _go(self, primary: str | None, phase: Phase, now: float, reason: str) -> None:
        st = self.state
        if (primary, phase) != (st.primary, st.phase):
            _logger.info("Selector: %s %s (%s)", primary, phase, reason)
            st.primary, st.phase, st.since = primary, phase.value, now
            self._run_since = self._idle_since = None
        self.reason = reason

    def _fail(self, src: str, now: float, why: str) -> None:
        self.state.failed[src] = now
        _logger.warning("Selector: %s failed: %s", src, why)
        self._go(_other(src), Phase.STEADY, now, f"{src} failed: {why}")

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Choose the heat sources."""
        cfg = self.cfg
        st = self.state
        old = (st.primary, st.phase, dict(st.failed))
        ov = {WP: inputs.get("override_wp"), PELLET: inputs.get("override_pellet")}
        allowed = {k: v is not False for k, v in ov.items()}

        for src in list(st.failed):
            if not self._blocked(src, now):
                del st.failed[src]

        if not allowed[WP] and not allowed[PELLET]:
            self._go(None, Phase.STEADY, now, "both sources off (override)")
        else:
            if st.primary is None:
                self._go(WP if allowed[WP] else PELLET, Phase.STEADY, now, "override released")
            prim = st.primary
            assert prim is not None
            # forced by an override?
            if not allowed[prim]:
                new = _other(prim)
                self._go(new, self._handover(new), now, f"{prim} off (override)")
            else:
                want = self._debounced(self._auto(inputs), now)
                if want is not None and want != prim and allowed[want]:
                    if self._blocked(want, now):
                        self.reason = f"{want} failed recently"
                    else:
                        self._go(want, self._handover(want), now, "temperatures")
            self._supervise(inputs, allowed, now)

        run = self._sources(st.primary, st.phase)
        for src in (WP, PELLET):
            if isinstance(v := ov[src], bool):
                run[src] = v
        out: dict[Path, Any] = {
            cfg.wanted: run[PELLET],
            out_path("selector"): {
                WP: run[WP],
                PELLET: run[PELLET],
                "primary": st.primary,
                "phase": st.phase,
                "reason": self.reason,
                "failed": sorted(st.failed),
            },
        }
        if cfg.feedback_pellet is not None:
            out[cfg.feedback_pellet] = run[PELLET]
        changed = (st.primary, st.phase, st.failed) != old
        wake = cfg.tick
        if self._cand is not None:
            wake = min(wake, max(self._cand_since + cfg.debounce - now, 0))
        return Step(outputs=out, wake_in=wake, save=changed, save_now=changed)

    @staticmethod
    def _handover(new: str) -> Phase:
        return Phase.WP_TO_PELLET if new == PELLET else Phase.PELLET_TO_WP

    @staticmethod
    def _sources(primary: str | None, phase: str) -> dict[str, bool]:
        if primary is None:
            return {WP: False, PELLET: False}
        if phase == Phase.STEADY:
            return {WP: primary == WP, PELLET: primary == PELLET}
        return {WP: True, PELLET: True}

    def _supervise(self, inputs: dict[str, Any], allowed: dict[str, bool], now: float) -> None:
        """Handover progress and fallback."""
        cfg = self.cfg
        st = self.state
        pellet = inputs.get("pellet") or {}
        pump = inputs.get("pump") or {}
        # A running burner may pause when the buffer is warm; in steady
        # state it has failed only if it doesn't run while heat is needed.
        tb_heat = _num(inputs.get("tb_heat"))
        t_low = _num(((inputs.get("target") or {}).get("demand") or {}).get("t_low"))
        cold = tb_heat is not None and t_low is not None and tb_heat < t_low
        watch = st.phase == Phase.WP_TO_PELLET or (
            st.primary == PELLET and st.phase == Phase.STEADY and cold
        )
        p_bad = self._pellet_bad(inputs, watch, now)
        wp_bad = self._wp_bad(inputs)

        if st.phase == Phase.WP_TO_PELLET:
            assert st.since is not None
            if p_bad is None and now - st.since > cfg.hot_timeout and not pellet.get("hot"):
                p_bad = "burner not hot in time"
            if p_bad is not None and allowed[WP]:
                self._fail(PELLET, now, p_bad)
            elif pellet.get("hot"):
                self._go(PELLET, Phase.STEADY, now, "burner hot")
            # a heat-pump error here changes nothing: the burner is coming

        elif st.phase == Phase.PELLET_TO_WP:
            if wp_bad is not None and allowed[PELLET]:
                self._fail(WP, now, wp_bad)
                return
            run = pump.get("run")
            if run == "run":
                self._idle_since = None
                if self._run_since is None:
                    self._run_since = now
                if now - self._run_since >= cfg.stable:
                    self._go(WP, Phase.STEADY, now, "heat pump runs")
            else:
                self._run_since = None
                if run == "off":
                    if self._idle_since is None:
                        self._idle_since = now
                    if now - self._idle_since >= cfg.idle_release:
                        self._go(WP, Phase.STEADY, now, "heat pump idle")
                else:
                    self._idle_since = None

        elif st.primary == WP:
            if wp_bad is not None and allowed[PELLET]:
                self._fail(WP, now, wp_bad)
        elif st.primary == PELLET:
            if p_bad is not None and allowed[WP]:
                self._fail(PELLET, now, p_bad)


class SelectorUnit(Unit[SelectorCfg, SelectorState]):
    """MoaT-Link adapter of the selector unit."""

    name = "selector"
    cfg_model = SelectorCfg
    state_model = SelectorState

    def make_core(self, cfg: SelectorCfg, state: SelectorState, now: float) -> SelectorCore:
        """The core."""
        return SelectorCore(cfg, state, now)

    def make_inputs(self, cfg: SelectorCfg) -> dict[str, Reader[Any]]:
        """Sensors, peer units, overrides."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in (
                "m_air",
                "m_air_pred",
                "pellet_state",
                "tb_water",
                "tb_heat",
                "tb_low",
                "cm_heat",
                "target",
                "pump",
                "pellet",
                "errors",
            )
        }
        rd["override_wp"] = override_reader(self.link, "wp", cfg.override_wp)
        rd["override_pellet"] = override_reader(self.link, "pellet", cfg.override_pellet)
        return rd
