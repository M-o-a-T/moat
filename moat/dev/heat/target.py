"""
The ``target`` unit: heating curve and demand (HEAT.md §3.1).

Port of the legacy ``run_set_heat`` and ``vt()``, plus the demand values
of ``run_pump``. The flow temperature follows the heating curve at the
outside temperature, towards the day or night room temperature, chosen
by a weekday/weekend schedule or by the day/night force switches. It is
written to the Solvis (``adj.curve.setting``) and published in
``app.heat.target.out``, together with the buffer temperatures the pump
unit aims for.
"""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003  # pydantic

import asyncclick as click

from moat.lib.config.base import BaseModel
from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)

from .config import UnitCfg
from .link import Reader, Switch, out_path
from .override import reader as override_reader
from .state import State
from .unit import Step, Unit

from typing import Any

__all__ = ["TargetCfg", "TargetCore", "TargetState", "TargetUnit", "cli", "schedule", "vt"]

_logger = logging.getLogger(__name__)

MAX_WAKE = 3600
"""Re-check the schedule at least this often, seconds (daylight saving changes)."""


class _WkWe(BaseModel):
    wk: float
    """Monday to Friday (start) or Sunday to Thursday (stop), hours."""
    we: float
    """Saturday and Sunday (start) or Friday and Saturday (stop), hours."""


class _Night(BaseModel):
    dest: float = 15
    """Room temperature at night."""
    start: _WkWe = _WkWe(wk=5.5, we=7)
    """End of the night (morning), hours."""
    stop: _WkWe = _WkWe(wk=21.5, we=23)
    """Start of the night (evening), hours."""


class CurveCfg(BaseModel):
    """The heating curve (legacy ``adj.curve``)."""

    dest: float = 21
    """Room temperature during the day."""
    max: float = 72
    """Flow temperature at an outside temperature of ``min``."""
    min: float = -15
    """Design outside temperature."""
    exp: float = 1.35
    """Curvature: 1 is linear."""
    night: _Night = _Night()


class _Force(BaseModel):
    cmd: Path
    """The switch."""
    state: Path | None = None
    """Its feedback."""


class _Adj(BaseModel):
    water: float = 2
    """``t_adj`` of the water circuit: ``c_water`` plus this."""
    heat: float = 1.5
    """``t_adj`` of the heating circuit: ``c_heat`` plus this."""
    low_water: float = 2
    """``t_low`` of the water circuit: ``c_water`` plus this."""
    low_heat: float = 1
    """``t_low`` of the heating circuit: ``c_heat`` plus this."""


class TargetCfg(UnitCfg):
    """Configuration of the target unit. Defaults: the production values."""

    # inputs
    t_ext: Path = P("temp.avg.temp.aussen_kompost.min")
    """Outside temperature for the curve (``adj.curve.current``)."""
    c_heat: Path = P("heat.s.heat.temp")
    """The Solvis' heating setpoint (``setting.heat.day``)."""
    c_water: Path = P("heat.s.water.temp")
    """The hot-water setpoint (``setting.water``)."""
    cm_heat: Path = P("app.heat.ha.heat")
    """Heating enabled (``cmd.heat``)."""
    override: Path = P("app.heat.override.flow_temp")
    """Operator override of the flow temperature (HEAT.md §2.7)."""
    force_day: _Force = _Force(
        cmd=P("app.heat.ha.force_day.cmd"),
        state=P("app.heat.ha.force_day.state"),
    )
    force_night: _Force = _Force(
        cmd=P("app.heat.ha.force_night.cmd"),
        state=P("app.heat.ha.force_night.state"),
    )

    # outputs
    setting: Path | None = P("heat.s.heat.temp.cmd")
    """The Solvis' flow setpoint (``adj.curve.setting``)."""

    curve: CurveCfg = CurveCfg()
    adj: _Adj = _Adj()

    max_age: float = 3600
    """The outside temperature is stale when it has not changed for this long, seconds."""
    freeze: float = 3600
    """Keep using a stale outside temperature this long, then use ``dest`` as flow temperature."""


class _Locks(BaseModel):
    day: bool = False
    night: bool = False


class TargetState(State):
    """Persistent state of the target unit: the force switches."""

    locks: _Locks = _Locks()


def vt(tau: float, ti: float, cf: CurveCfg) -> float:
    """
    The heating curve: the flow temperature at outside temperature ``tau``
    for room temperature ``ti``.
    """
    if tau >= ti:
        return ti
    return ti + (cf.max - ti) * pow((ti - tau) / (ti - cf.min), 1 / cf.exp)


def schedule(cf: CurveCfg, local: datetime) -> tuple[bool, float]:
    """
    The night schedule.

    As in the legacy code, the weekend start time applies on Saturdays and
    Sundays, the weekend stop time on Fridays and Saturdays.

    Returns:
        Whether it's day, and the seconds until that changes (or until
        midnight).
    """
    wd = local.weekday()  # 0: Monday
    h = local.hour + local.minute / 60 + local.second / 3600 + local.microsecond / 3.6e9
    n = cf.night
    s1 = n.start.wk if wd < 5 else n.start.we
    if h < s1:
        return False, (s1 - h) * 3600
    s2 = n.stop.wk if wd not in (4, 5) else n.stop.we
    if h < s2:
        return True, (s2 - h) * 3600
    return False, (24 - h) * 3600


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


class TargetCore:
    """
    Sans-IO core of the target unit.

    Inputs: ``t_ext``, ``c_heat``, ``c_water``, ``cm_heat``, ``override``,
    ``force_day`` and ``force_night`` (`~moat.dev.heat.link.Switch`
    values), and ``local`` (the local time; without
    it, it's always day).

    The outside temperature is stale when it has not changed for
    ``max_age`` seconds (values are published on change); its last value
    is used for another ``freeze`` seconds, then the flow temperature
    drops to the room temperature (the curve's lower end).
    """

    def __init__(self, cfg: TargetCfg, state: TargetState, now: float) -> None:
        self.cfg = cfg
        self.state = state
        self._seen: dict[str, Any] = {}
        self._raw: float | None = None
        self._t_ext: float | None = None
        self._t_ext_changed = now

    def update_cfg(self, cfg: TargetCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def _force(self, inputs: dict[str, Any], out: dict[Path, Any]) -> bool:
        """
        Process the force switches; returns whether the locks changed.

        Each switch input is ``(state, n)`` (see `~moat.dev.heat.link.Switch`):
        only a change of ``n``, i.e. by someone else, is acted upon.
        """
        locks = self.state.locks
        old = (locks.day, locks.night)
        for dn, nd in (("day", "night"), ("night", "day")):
            sw = inputs.get(f"force_{dn}")
            if sw is None:
                continue
            v, n = sw
            if self._seen.get(dn) == n:
                continue
            self._seen[dn] = n
            me: _Force = getattr(self.cfg, f"force_{dn}")
            other: _Force = getattr(self.cfg, f"force_{nd}")
            if v is None or out.get(me.cmd) is False:
                # deleted, or both were switched on at once and the other won
                continue
            v = bool(v)
            if me.state is not None:
                out[me.state] = v
            if v:
                osw = inputs.get(f"force_{nd}")
                if osw is not None and osw[0]:
                    out[other.cmd] = False
                if other.state is not None:
                    out[other.state] = False
                setattr(locks, nd, False)
            setattr(locks, dn, v)
        return (locks.day, locks.night) != old

    def _outside(self, t_ext: float | None, now: float) -> tuple[float | None, bool, float]:
        """The outside temperature to use, whether it's stale, and when to check again."""
        cfg = self.cfg
        if t_ext != self._raw:
            self._raw = t_ext
            self._t_ext_changed = now
            if t_ext is not None:
                self._t_ext = t_ext
        if t_ext is None:
            stale_since = self._t_ext_changed
        else:
            stale_since = self._t_ext_changed + cfg.max_age
            if now < stale_since:
                return t_ext, False, stale_since - now
        if self._t_ext is not None and now < stale_since + cfg.freeze:
            return self._t_ext, True, stale_since + cfg.freeze - now
        return None, True, MAX_WAKE

    def _demand(self, inputs: dict[str, Any]) -> dict[str, Any] | None:
        """The buffer temperatures to aim for (legacy ``run_pump``)."""
        adj = self.cfg.adj
        cw, ch = _num(inputs.get("c_water")), _num(inputs.get("c_heat"))
        if cw is None:
            return None
        tw_nom, tw_low, tw_adj = cw, cw + adj.low_water, cw + adj.water
        if inputs.get("cm_heat") and ch is not None:
            th_nom, th_low, th_adj = ch, ch + adj.low_heat, ch + adj.heat
            return {
                "t_nom": max(th_nom, tw_nom),
                "t_low": max(th_low, tw_low),
                "t_adj": max(th_adj, tw_adj),
                "t_set_on": max(tw_nom, th_nom),
                "t_set_off": max(tw_nom, th_low),
                "source": "heat",
            }
        return {
            "t_nom": tw_nom,
            "t_low": tw_low,
            "t_adj": tw_adj,
            "t_set_on": tw_nom,
            "t_set_off": tw_nom,
            "source": "water",
        }

    def step(self, inputs: dict[str, Any], now: float) -> Step:
        """Compute the flow temperature and the demand."""
        cfg = self.cfg
        cf = cfg.curve
        out: dict[Path, Any] = {}
        save = self._force(inputs, out)

        local = inputs.get("local")
        if local is None:
            day, wake = True, MAX_WAKE
        else:
            day, wake = schedule(cf, local)
            wake = min(wake + 1, MAX_WAKE)
        locks = self.state.locks
        if locks.day:
            day = True
        elif locks.night:
            day = False
        dest = cf.dest if day else cf.night.dest

        t_ext, stale, w = self._outside(_num(inputs.get("t_ext")), now)
        wake = min(wake, w)
        computed = dest if t_ext is None else vt(t_ext, dest, cf)
        ovr = _num(inputs.get("override"))
        flow_temp = computed if ovr is None else ovr

        if cfg.setting is not None:
            out[cfg.setting] = int(flow_temp + 0.8)
        out[out_path("target")] = {
            "flow_temp": flow_temp,
            "flow_temp_computed": computed,
            "overridden": ovr is not None,
            "day_active": day,
            "t_ext": t_ext,
            "t_ext_stale": stale,
            "demand": self._demand(inputs),
        }
        return Step(outputs=out, wake_in=wake, save=save)


class TargetUnit(Unit[TargetCfg, TargetState]):
    """MoaT-Link adapter of the target unit."""

    name = "target"
    cfg_model = TargetCfg
    state_model = TargetState
    local_time = True

    def make_core(self, cfg: TargetCfg, state: TargetState, now: float) -> TargetCore:
        """The core."""
        return TargetCore(cfg, state, now)

    def make_inputs(self, cfg: TargetCfg) -> dict[str, Reader[Any]]:
        """Outside temperature, setpoints, switches, override."""
        rd: dict[str, Reader[Any]] = {
            k: Reader[Any](self.link, getattr(cfg, k))
            for k in ("t_ext", "c_heat", "c_water", "cm_heat")
        }
        rd["force_day"] = Switch(self.link, cfg.force_day.cmd)
        rd["force_night"] = Switch(self.link, cfg.force_night.cmd)
        rd["override"] = override_reader(self.link, "flow_temp", cfg.override)
        return rd


def curve_table(cf: CurveCfg, step: int = 1) -> list[tuple[int, float, float]]:
    """``(outside temperature, day flow temperature, night flow temperature)`` rows."""
    return [
        (t, vt(t, cf.dest, cf), vt(t, cf.night.dest, cf))
        for t in range(int(cf.min), int(cf.night.dest), step)
    ]


@click.group(short_help="The heating curve and demand unit.")
async def cli() -> None:
    """The ``target`` unit (heating curve and demand)."""


@cli.command()
@click.option(
    "-d", "--defaults", is_flag=True, help="Use the package defaults, don't ask MoaT-Link."
)
@click.pass_obj
async def curve(obj: Any, defaults: bool) -> None:
    """Show the heating curve: outside, day and night flow temperature."""
    from .config import load_config, make_config  # noqa: PLC0415

    if defaults:
        cfg = make_config("target", TargetCfg)
    else:
        from moat.link.client import Link  # noqa: PLC0415

        async with Link(obj.cfg.link) as link:
            cfg = await load_config(link, "target", TargetCfg)
    for t, d, n in curve_table(cfg.curve):
        print(f"{t:3d} {d:.1f} {n:.1f}")
