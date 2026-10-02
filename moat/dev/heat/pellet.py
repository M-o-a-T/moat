"""
The ``pellet`` unit: the pellet burner's load (HEAT.md §3.5).

Port of the legacy ``run_set_pellet`` plus the pellet writes of
``run_pump``. The burner is switched on and off by the selector
(``cmd.pellet.wanted``); this unit only tells a running burner how hard to
work (``cmd.pellet.load``), which temperature to aim for
(``cmd.pellet.temp``) and, while it starts, which goals to patch into its
controller.
"""

from __future__ import annotations

from enum import StrEnum

from moat.util import pos2val, val2pos
from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)
from moat.util.time import time

from .config import UnitCfg
from .link import Reader, out_path
from .override import reader as override_reader
from .pid import APID, PIDCfg, PIDState
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = [
    "Mode",
    "PelletCfg",
    "PelletCore",
    "PelletState",
    "PelletUnit",
    "classify",
]


class Mode(StrEnum):
    """What the burner does, from its KWB state code."""

    OFF = "off"
    STARTING = "starting"
    RUNNING = "running"
    """Codes 2 and 4. The load is controlled only in this mode."""


def classify(code: int) -> Mode:
    """Classify a KWB state code (legacy ``run_set_pellet``)."""
    if code in (0, 1, 3, 5, 6, 7, 8, 9) or 21 <= code <= 35 or code >= 43:
        return Mode.OFF
    if code not in (2, 4):
        return Mode.STARTING
    return Mode.RUNNING


class _Startup(BaseModel):
    buf: float = 5
    """While starting, aim for the warmer buffer sensor plus this (``adj.pellet.startup.buf``)."""
    patch: list[Path] = [
        P("heat.s.pellets.aux:1.goal"),
        P("heat.s.pellets.aux:2.goal"),
        P("heat.s.pellets.aux.r-min.goal"),
    ]
    """Goals in the burner's controller that get the start-up temperature."""
    stop: float = 65
    """… and this value once the burner runs."""


class _Adj(BaseModel):
    load: float = 3
    """``t_load = t_adj + load`` (``adj.pellet.load``)."""
    max: float = 75
    """Maximum ``t_load`` (``adj.pellet.max``)."""
    low: float = 15
    """Full load (preload) while ``tb_heat`` is this far below ``t_load`` (``adj.pellet.low``)."""
    preload_low: float = 2
    """Preload point while far below, as a fraction from ``tb_heat`` to ``t_load``."""
    preload_wp: float = 3.5
    """Preload point while the heat pump runs, likewise."""
    more: float = 2
    """``tp_limit = t_adj + more``; also the width of the load/buffer blend (``adj.more``)."""
    max_temp: float = 75
    """Maximum burner temperature request (``adj.max_pellet``)."""
    low_factor: float = 0.4
    """How much a buffer below ``t_low`` raises the temperature request (``adj.low.factor``)."""
    low_buffer: float = -5
    """``t_buffer = t_low + low_buffer`` (``adj.low.buffer``)."""


class PelletCfg(UnitCfg):
    """Configuration of the pellet unit. Defaults: the production values."""

    # inputs
    state: Path = P("heat.s.pellets.state")
    """The burner's KWB state code (``sensor.pellet.state``)."""
    tb_water: Path = P("heat.s.buffer.temp.water")
    tb_heat: Path = P("heat.s.buffer.temp.heat")
    tb_mid: Path = P("heat.s.buffer.temp.mid")
    tb_low: Path = P("heat.s.buffer.temp.return")
    t_pellet: Path = P("heat.s.pellets.temp.top")
    """The burner's temperature (``sensor.temp.pellet``)."""
    force: Path = P("heat.s.pellets.load.force")
    """A load to use instead of the controller's (``cmd.pellet.force``)."""
    target: Path = out_path("target")
    selector: Path = out_path("selector")
    pump: Path = out_path("pump")
    override: Path = P("app.heat.override.pellet")

    # outputs
    load: Path = P("heat.s.pellets.load.goal.cmd")
    """The burner's load (``cmd.pellet.load``)."""
    temp: Path = P("heat.s.pellets.temp.goal.cmd")
    """The burner's temperature goal (``cmd.pellet.temp``)."""

    t_min: float = 10000
    """The burner is settled after running this long, seconds (``lim.pellet.t_min``)."""
    temp_min: float = 60
    """Never ask for less than this temperature (``lim.pellet.temp.min``)."""
    hot_delta: float = 0
    """``hot`` once the burner is at least ``t_adj`` plus this."""
    tick: float = 10
    """Step interval while the burner runs, seconds."""

    startup: _Startup = _Startup()
    adj: _Adj = _Adj()

    p_load: PIDCfg = PIDCfg()
    """``tb_heat`` → load."""
    p_buffer: PIDCfg = PIDCfg()
    """``tb_low`` → load (limits the load when the buffer bottom gets warm)."""


class PelletPids(BaseModel):
    """The PIDs' persistent state."""

    p_load: PIDState = PIDState()
    p_buffer: PIDState = PIDState()


class PelletState(State):
    """Persistent state of the pellet unit."""

    t_pellet_on: bool | float = False
    """
    `False` while the burner is off, `True` once it has settled.

    In between, the wall-clock time when it started.
    """
    pellet_on: bool = False
    """The burner has been seen running (code 4) since it last started."""
    load: float = 0
    """The last controlled load."""
    pids: PelletPids = PelletPids()


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class PelletCore:
    """
    Sans-IO core of the pellet unit.

    Inputs: ``state`` (KWB code), the buffer sensors ``tb_water``,
    ``tb_heat``, ``tb_mid``, ``tb_low``, ``t_pellet``, ``force``, and the
    ``target``, ``selector`` and ``pump`` units' outputs, and ``override``.

    The burner is wanted when ``override`` says so, else when
    ``selector.pellet`` does. Switching it on presets both PIDs to full
    load; switching it off resets ``t_pellet_on`` and the load. A forced
    off (``override`` `False`) also sets the load to 0.
    """

    SENSORS = ("tb_water", "tb_heat", "tb_mid", "tb_low")

    def __init__(self, cfg: PelletCfg, state: PelletState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        self.pid_load = APID(cfg.p_load, state.pids.p_load, now)
        self.pid_buffer = APID(cfg.p_buffer, state.pids.p_buffer, now)
        self._wanted: bool | None = None
        self._branch = ""

    def update_cfg(self, cfg: PelletCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg
        self.pid_load.update_cfg(cfg.p_load)
        self.pid_buffer.update_cfg(cfg.p_buffer)

    def _limits(self, v: dict[str, float], dem: dict[str, Any]) -> tuple[float, float]:
        "``tp_limit`` (legacy run_pump) and the start-up temperature"
        a = self.cfg.adj
        t_cur = v["tb_heat"] if dem.get("source", "heat") == "heat" else v["tb_water"]
        tp_limit = min(a.max_temp, dem["t_adj"] + a.more)
        if t_cur < dem["t_low"]:
            tp_limit += (dem["t_low"] - t_cur) * a.low_factor
        start = min(a.max_temp, self.cfg.startup.buf + max(v["tb_water"], v["tb_heat"]))
        return tp_limit, start

    def _edges(self, wanted: bool | None, v: dict[str, float], now: float) -> bool:
        "react to the burner being switched on or off; returns whether the state changed"
        old, self._wanted = self._wanted, wanted
        if old is None or bool(old) == bool(wanted):
            return False
        if wanted:
            self.pid_load.move_to(v["tb_heat"], 1.0, now)
            self.pid_buffer.move_to(v["tb_low"], 1.0, now)
            self._branch = "on"
        else:
            self.state.t_pellet_on = False
            self.state.load = 0
            self._branch = "off"
        return True

    def _control(
        self, v: dict[str, float], dem: dict[str, Any], inputs: dict[str, Any], now: float
    ) -> float:
        "the load while the burner runs (legacy run_set_pellet, branches F/B/C/-)"
        a = self.cfg.adj
        t_adj = dem["t_adj"]
        t_load = min(t_adj + a.load, a.max)
        tb_heat = v["tb_heat"]
        self.pid_load.setpoint(t_load)
        self.pid_buffer.setpoint(dem["t_low"] + a.low_buffer)

        l_buffer = self.pid_buffer(v["tb_low"], now)
        w = val2pos(t_adj - a.more, tb_heat, t_adj)
        l_load = self.pid_load(tb_heat, now)

        pump = inputs.get("pump")
        wp_on = isinstance(pump, dict) and pump.get("run") == "run"
        force = _num(inputs.get("force"))
        if force is not None:
            self._branch = "F"
            self.pid_load.move_to(tb_heat, force, now)
            return force
        if tb_heat + a.low < t_load:
            self._branch = "B"
            self.pid_load.move_to(tb_heat + (t_load - tb_heat) * a.preload_low, 1.0, now)
            return 1.0
        if wp_on:
            self._branch = "C"
            self.pid_load.move_to(tb_heat + (t_load - tb_heat) * a.preload_wp, 1.0, now)
            return 1.0
        self._branch = "-"
        return min(pos2val(l_load, w, l_buffer, clamp=True), l_load)

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Decide the burner's load and temperature."""
        cfg = self.cfg
        st = self.state
        outputs: dict[Path, Any] = {}

        v = {k: _num(inputs.get(k)) for k in self.SENSORS}
        code = _num(inputs.get("state"))
        target = inputs.get("target")
        dem = target.get("demand") if isinstance(target, dict) else None
        missing = [k for k, x in v.items() if x is None]
        if code is None:
            missing.append("state")
        if missing or not dem:
            reason = "missing: " + ",".join(missing or ["demand"])
            outputs[out_path("pellet")] = self._out(None, False, reason, inputs)
            return Step(outputs=outputs, wake_in=cfg.tick)
        vals: dict[str, float] = {k: x for k, x in v.items() if x is not None}

        ovr = inputs.get("override")
        sel = inputs.get("selector")
        wanted = (
            ovr
            if isinstance(ovr, bool)
            else (bool(sel.get("pellet")) if isinstance(sel, dict) else None)
        )
        save = self._edges(wanted, vals, now)
        old = (st.t_pellet_on, st.pellet_on, st.load)

        mode = classify(int(code))
        tp_limit, start = self._limits(vals, dem)
        used = False
        if mode == Mode.OFF:
            st.t_pellet_on = False
            st.pellet_on = False
            self._branch = "off"
        elif mode == Mode.STARTING:
            st.pellet_on = False
            st.t_pellet_on = time()
            self._branch = "starting"
        else:
            if code == 4:
                st.pellet_on = True
                t_on = st.t_pellet_on
                # legacy: ``time - False`` is large, so running without a
                # start phase counts as settled at once
                if t_on is not True and (t_on is False or time() - t_on > cfg.t_min):
                    st.t_pellet_on = True
            if ovr is False:
                self._branch = "override"
                st.load = 0
            else:
                st.load = self._control(vals, dem, inputs, now)
                used = True

        if st.pellet_on:
            outputs[cfg.temp] = max(cfg.temp_min, tp_limit)
            for p in cfg.startup.patch:
                outputs[p] = cfg.startup.stop
            outputs[cfg.load] = st.load
        else:
            # not running yet: full load, and a higher goal to get it going
            outputs[cfg.temp] = max(cfg.temp_min, start)
            for p in cfg.startup.patch:
                outputs[p] = start
            outputs[cfg.load] = 0 if ovr is False else 1

        for pid in (self.pid_load, self.pid_buffer):
            if not used and pid.state.t != now:
                pid.idle(now)
            outputs.update(pid.logs)
            pid.logs.clear()

        hot = bool(
            st.pellet_on
            and (tp := _num(inputs.get("t_pellet"))) is not None
            and tp >= dem["t_adj"] + cfg.hot_delta
        )
        outputs[out_path("pellet")] = self._out(mode, hot, self._branch, inputs)
        save = save or used or (st.t_pellet_on, st.pellet_on, st.load) != old
        wake = cfg.tick if mode != Mode.OFF else None
        return Step(outputs=outputs, wake_in=wake, save=save)

    def _out(
        self, mode: Mode | None, hot: bool, reason: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        st = self.state
        return {
            "t_pellet_on": st.t_pellet_on,
            "pellet_on": st.pellet_on,
            "load": st.load,
            "hot": hot,
            "mode": None if mode is None else str(mode),
            "state_code": inputs.get("state"),
            "reason": reason,
        }


class PelletUnit(Unit[PelletCfg, PelletState]):
    """
    Set the pellet burner's load and temperature.

    This is the MoaT-Link adapter of the pellet unit.
    """

    name = "pellet"
    cfg_model = PelletCfg
    state_model = PelletState

    def make_core(self, cfg: PelletCfg, state: PelletState, now: float) -> PelletCore:
        """The core."""
        return PelletCore(cfg, state, now)

    def make_inputs(self, cfg: PelletCfg) -> dict[str, Reader[Any]]:
        """Burner state, buffer sensors, force input, peer outputs, override."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in (
                "state",
                "tb_water",
                "tb_heat",
                "tb_mid",
                "tb_low",
                "t_pellet",
                "force",
                "target",
                "selector",
                "pump",
            )
        }
        rd["override"] = override_reader(self.link, "pellet", cfg.override)
        return rd
