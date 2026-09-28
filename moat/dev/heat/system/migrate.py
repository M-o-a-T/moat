"""
One-shot migration of the legacy controller's configuration and state to
the units' MoaT-Link items (HEAT.md §4.1).

The legacy configuration is the built-in defaults (``legacy.yaml``, the
``CFG`` literal of ``solvis.py``) overlaid with the production YAML file.
Every key is mapped through `_CFG_MAP` to the units' configuration
items; a key that is neither mapped nor explicitly dropped is an error.
Only values that differ from a unit's package defaults are written, so
later changes of the defaults still apply.

The legacy state (one mapping, stored in MoaT-KV or a file) is split
into the units' ``app.heat.<unit>.state`` items.

This module does not import ``solvis.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path as FSPath

from moat.util import NotGiven, attrdict, combine_dict, yload, yprint
from moat.dev.heat.config import (
    CFG_PATH,
    EmergencyCfg,
    ServiceCfg,
    UnitCfg,
    defaults,
    make_config,
)
from moat.dev.heat.errors import ErrorsCfg
from moat.dev.heat.flow import FlowCfg
from moat.dev.heat.frost import FrostCfg
from moat.dev.heat.heat_valve import HeatValveCfg
from moat.dev.heat.pellet import PelletCfg
from moat.dev.heat.pump import PumpCfg
from moat.dev.heat.pwm import PwmCfg
from moat.dev.heat.selector import SelectorCfg
from moat.dev.heat.state import state_path
from moat.dev.heat.target import TargetCfg
from moat.dev.heat.watchdog import WatchdogCfg

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

__all__ = [
    "MODELS",
    "MigrateError",
    "Migration",
    "dropped",
    "legacy_config",
    "map_config",
    "map_state",
    "migrate",
]

_logger = logging.getLogger(__name__)

LEGACY = FSPath(__file__).parent / "legacy.yaml"

MODELS: dict[str, type[UnitCfg]] = {
    "target": TargetCfg,
    "heat_valve": HeatValveCfg,
    "flow": FlowCfg,
    "pump": PumpCfg,
    "pellet": PelletCfg,
    "selector": SelectorCfg,
    "errors": ErrorsCfg,
    "watchdog": WatchdogCfg,
    "frost": FrostCfg,
    "emergency": EmergencyCfg,
    "service": ServiceCfg,
    "pwm": PwmCfg,
}
"""The configuration model of every unit (and support item) that the migration writes."""


class MigrateError(ValueError):
    """The legacy data can't be migrated."""


@dataclass(frozen=True)
class Drop:
    """A legacy key that is not migrated, and why."""

    why: str


Target: TypeAlias = tuple[str, str]
"""``(unit, dotted path in the unit's configuration)``"""

_CFG_MAP: dict[str, list[Target] | Drop] = {
    # the location of the legacy state: an input of the migration
    "state": Drop("location of the legacy state (read by the migration)"),
    # adj
    "adj.water": [("target", "adj.water")],
    "adj.heat": [("target", "adj.heat")],
    "adj.more": [("pump", "adj.more"), ("pellet", "adj.more")],
    "adj.max": [("pump", "adj.max")],
    "adj.max_max": [("pump", "adj.max_max"), ("flow", "max_max")],
    "adj.max_pellet": [("pellet", "adj.max_temp")],
    "adj.buffer": [("pump", "adj.buffer")],
    "adj.pellet.pid.load.p": [("pump", "load_pellet.p")],
    "adj.pellet.pid.load.i": [("pump", "load_pellet.i")],
    "adj.pellet.pid.load.d": [("pump", "load_pellet.d")],
    "adj.pellet.pid.load.tf": [("pump", "load_pellet.tf")],
    "adj.pellet.load": [("pump", "adj.pellet_load"), ("pellet", "adj.load")],
    "adj.pellet.low": [("pellet", "adj.low")],
    "adj.pellet.preload.low": [("pellet", "adj.preload_low")],
    "adj.pellet.preload.wp": [("pellet", "adj.preload_wp")],
    "adj.pellet.max": [("pump", "adj.pellet_max"), ("pellet", "adj.max")],
    "adj.pellet.startup.buf": [("pellet", "startup.buf")],
    "adj.pellet.startup.patch.path": [("pellet", "startup.patch")],
    "adj.pellet.startup.patch.stop": [("pellet", "startup.stop")],
    "adj.low.water": [("target", "adj.low_water")],
    "adj.low.heat": [("target", "adj.low_heat")],
    "adj.low.buffer": [("pump", "adj.low_buffer"), ("pellet", "adj.low_buffer")],
    "adj.low.factor": [("pump", "adj.low_factor"), ("pellet", "adj.low_factor")],
    "adj.low.pwm": [("heat_valve", "low_pwm")],
    "adj.low.pre_heat": [("heat_valve", "pre_heat")],
    "adj.curve.dest": [("target", "curve.dest")],
    "adj.curve.max": [("target", "curve.max")],
    "adj.curve.min": [("target", "curve.min")],
    "adj.curve.exp": [("target", "curve.exp")],
    "adj.curve.current": [("target", "t_ext")],
    "adj.curve.setting": [("target", "setting")],
    "adj.curve.night.dest": [("target", "curve.night.dest")],
    "adj.curve.night.start.wk": [("target", "curve.night.start.wk")],
    "adj.curve.night.start.we": [("target", "curve.night.start.we")],
    "adj.curve.night.stop.wk": [("target", "curve.night.stop.wk")],
    "adj.curve.night.stop.we": [("target", "curve.night.stop.we")],
    # output
    "output.flow.pin": [("pwm", "outputs.flow.pin")],
    "output.flow.freq": [("pwm", "outputs.flow.freq")],
    "output.flow.path": [("pwm", "outputs.flow.path"), ("flow", "output")],
    "output.flow.inverted": [("pwm", "outputs.flow.inverted")],
    "output.flow.override.flag": [("pwm", "outputs.flow.override.flag")],
    "output.flow.override.val": [("pwm", "outputs.flow.override.val")],
    # sensor
    "sensor.pump.in": [
        ("pump", "t_in"),
        ("flow", "t_in"),
        ("frost", "t_in"),
        ("watchdog", "t_in"),
        ("emergency", "sensor_in"),
    ],
    "sensor.pump.out": [
        ("pump", "t_out"),
        ("flow", "t_out"),
        ("heat_valve", "t_out"),
        ("frost", "t_out"),
        ("watchdog", "t_out"),
        ("emergency", "sensor_out"),
    ],
    "sensor.pump.flow": [("pump", "r_flow"), ("flow", "r_flow")],
    "sensor.pump.ice": [("pump", "m_ice")],
    "sensor.pump.state": Drop("deprecated"),
    "sensor.buffer.top": [("pump", "tb_water"), ("pellet", "tb_water"), ("selector", "tb_water")],
    "sensor.buffer.heat": [
        ("pump", "tb_heat"),
        ("pellet", "tb_heat"),
        ("selector", "tb_heat"),
        ("heat_valve", "tb_heat"),
    ],
    "sensor.buffer.mid": [("pump", "tb_mid"), ("pellet", "tb_mid")],
    "sensor.buffer.low": [
        ("pump", "tb_low"),
        ("pellet", "tb_low"),
        ("selector", "tb_low"),
        ("heat_valve", "tb_low"),
    ],
    "sensor.error": [("errors", "feed")],
    "sensor.power": [("pump", "m_power")],
    "sensor.cop": [("pump", "cop_out")],
    "sensor.temp.current": [("selector", "m_air")],
    "sensor.temp.predict": [("selector", "m_air_pred")],
    "sensor.temp.pellet": [("pellet", "t_pellet")],
    "sensor.temp.heat": [("pump", "t_heat")],
    "sensor.pellet.state": [("pellet", "state"), ("selector", "pellet_state")],
    # setting
    "setting.heat.day": [("target", "c_heat"), ("pump", "c_heat"), ("heat_valve", "c_heat")],
    "setting.heat.night": Drop("unused; the night setback is the target unit's curve"),
    "setting.heat.mode.path": [("heat_valve", "mode")],
    "setting.heat.mode.on": [("heat_valve", "mode_on")],
    "setting.heat.mode.off": [("heat_valve", "mode_off")],
    "setting.heat.mode.delay": [("heat_valve", "delay")],
    "setting.heat.mode.force.day.cmd": [("target", "force_day.cmd")],
    "setting.heat.mode.force.day.state": [("target", "force_day.state")],
    "setting.heat.mode.force.night.cmd": [("target", "force_night.cmd")],
    "setting.heat.mode.force.night.state": [("target", "force_night.state")],
    "setting.heat.power.pin": Drop(
        "GPIO heat pin: use a pwm daemon output driven by heat_valve.pin instead"
    ),
    "setting.water": [("target", "c_water"), ("pump", "c_water")],
    "setting.passthru": Drop("unused override; passthru is app.heat.passthru.request"),
    # lim
    "lim.flow.min": Drop("unused"),
    "lim.power.min": [("pump", "min_load")],
    "lim.power.off": Drop("unused"),
    "lim.power.time": [("pump", "min_run")],
    "lim.times.start": [("pump", "times.start")],
    "lim.times.ice": [("pump", "times.ice")],
    "lim.times.stop": [("pump", "times.stop")],
    "lim.low.scale": [("pump", "low.scale")],
    "lim.low.limit": [("pump", "low.limit")],
    "lim.low.pellet.scale": [("pump", "low.pellet_scale")],
    "lim.low.pellet.limit": [("pump", "low.pellet_limit")],
    "lim.pellet.stop.buffer": [("pump", "pellet_start.stop_buffer")],
    "lim.pellet.start.buffer": [("pump", "pellet_start.buffer")],
    "lim.pellet.start.heat.delta": [("pump", "pellet_start.heat_delta")],
    "lim.pellet.start.heat.scale": [("pump", "pellet_start.heat_scale")],
    "lim.pellet.t_min": [("pellet", "t_min")],
    "lim.pellet.temp.min": [("pellet", "temp_min")],
    "lim.start": [("pump", "pellet_start.max_low")],
    "lim.defrost.temp": [("pump", "stop.defrost_temp")],
    "lim.defrost.flow": Drop("frost protection is the frost unit"),
    "lim.idle": [("pump", "stop.idle")],
    # cmd
    "cmd.bypass.cmd": Drop("bypass mode is replaced by overrides and passthru"),
    "cmd.bypass.mode": Drop("bypass mode is replaced by overrides and passthru"),
    "cmd.bypass.power": Drop("bypass mode is replaced by overrides and passthru"),
    "cmd.flow": Drop("bypass mode is replaced by overrides and passthru"),
    "cmd.wp": Drop("mapped onto app.heat.override.wp by the Home Assistant bridge"),
    "cmd.heat": [("target", "cm_heat"), ("heat_valve", "cm_heat"), ("selector", "cm_heat")],
    "cmd.mode.path": [("pump", "mode"), ("emergency", "mode_path")],
    "cmd.mode.on": [("pump", "mode_on")],
    "cmd.mode.off": [("pump", "mode_off"), ("emergency", "mode_off")],
    "cmd.power": [("pump", "power"), ("emergency", "power_path")],
    "cmd.pellet.force": [("pellet", "force")],
    "cmd.pellet.temp": [("pellet", "temp")],
    "cmd.pellet.load": [("pellet", "load")],
    "cmd.pellet.wanted": [("selector", "wanted")],
    "cmd.pellet.switch": Drop("mapped onto app.heat.override.pellet by the Home Assistant bridge"),
    "cmd.pellet.run": Drop("driven from cmd.pellet.wanted by a MoaT-KV rule"),
    "cmd.passthru.pump": Drop("deprecated"),
    "cmd.passthru.pellet": Drop("deprecated"),
    # feedback
    "feedback.wp": [("pump", "feedback_wp")],
    "feedback.heat": [("heat_valve", "feedback_heat")],
    "feedback.pump": [("heat_valve", "feedback_pump")],
    "feedback.ice": [("pump", "feedback_ice")],
    "feedback.pellet": [("selector", "feedback_pellet")],  # commented out in production
    "feedback.main": Drop("unused"),
    "feedback.bypass": Drop("deprecated"),
    "feedback.passthru.pump": Drop("deprecated"),
    "feedback.passthru.pellet": Drop("deprecated"),
    # misc
    "misc.switch.state": [("heat_valve", "m_switch")],
    "misc.pellet.current": [("selector", "current")],
    "misc.pellet.predict": [("selector", "predict")],
    "misc.pellet.avg_off": [("selector", "avg_off")],
    "misc.init_timeout": Drop("unused: units wait for their inputs"),
    "misc.de_ice.flow": [("pump", "de_ice.flow")],
    "misc.de_ice.pwm": [("pump", "de_ice.pwm")],
    "misc.de_ice.min": [("pump", "de_ice.min_pwm")],
    "misc.stop.flow": [("pump", "stop.flow")],
    "misc.stop.delta": [
        ("pump", "stop.delta"),
        ("flow", "stop_delta"),
        ("emergency", "stop_delta"),
    ],
    "misc.start.delay": [("pump", "start.delay")],
    "misc.start.flow.init.rate": [("pump", "start.init.rate")],
    "misc.start.flow.init.pwm": [("pump", "start.init.pwm")],
    "misc.start.flow.power.rate": [("pump", "start.power.rate")],
    "misc.start.flow.power.pwm": [("pump", "start.power.pwm")],
    "misc.start.flow.run": Drop("unused"),
    "misc.start.power": [("pump", "start.load")],
    "misc.start.delta": [("pump", "start.delta")],
    "misc.min_power": [("pump", "start.min_power")],
    "misc.heat.delta": [("pump", "adj.heat_delta"), ("heat_valve", "heat_delta")],
}

_PIDS: dict[str, Target] = {
    "flow": ("flow", "flow"),
    "pump": ("flow", "pump"),
    "load": ("pump", "load"),
    "buffer": ("pump", "buffer"),
    "limit": ("pump", "limit"),
    "p_load": ("pellet", "p_load"),
    "p_buffer": ("pellet", "p_buffer"),
}
"""Legacy PID → the unit and field that holds its configuration."""

_PID_FIELDS = ("p", "i", "d", "tf", "min", "max", "factor", "offset", "log.value", "log.setpoint")

for _pid, (_unit, _field) in _PIDS.items():
    for _k in _PID_FIELDS:
        _tgt: list[Target] = [(_unit, f"{_field}.{_k}")]
        if _pid == "load":
            # the pump's pellet gains are the load PID's, except for adj.pellet.pid.load
            _tgt.append(("pump", f"load_pellet.{_k}"))
        _CFG_MAP[f"pid.{_pid}.{_k}"] = _tgt
    _CFG_MAP[f"pid.{_pid}.state"] = Drop("state slot name; the state is split by the migration")

_OVERRIDES_FIRST = ("adj.pellet.pid.load.",)
"""Keys that are applied last, so that they override other keys' values for the same field."""


def legacy_config(prod: str | None = None, base: str | None = None) -> attrdict:
    """
    The legacy configuration: built-in defaults overlaid with the production YAML.

    Args:
        prod: The production YAML text.
        base: The defaults (default: ``legacy.yaml``).
    """
    cfg = yload(LEGACY.read_text() if base is None else base, attr=True)
    if prod:
        cfg = combine_dict(yload(prod, attr=True), cfg, cls=attrdict)
    return cfg


def _leaves(d: Mapping[str, Any], pre: str = "") -> list[tuple[str, Any]]:
    res = []
    for k, v in d.items():
        p = f"{pre}.{k}" if pre else str(k)
        if isinstance(v, Mapping) and v:
            res.extend(_leaves(v, p))
        else:
            res.append((p, v))
    return res


def _set(d: dict[str, Any], dotted: str, value: Any) -> None:
    *pre, last = dotted.split(".")
    for k in pre:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[last] = value


def _diff(new: Any, old: Any) -> Any:
    """The parts of ``new`` that differ from ``old`` (`NotGiven` if none)."""
    if isinstance(new, dict) and isinstance(old, dict):
        res = {}
        for k, v in new.items():
            d = _diff(v, old.get(k, NotGiven))
            if d is not NotGiven:
                res[k] = d
        return res or NotGiven
    return NotGiven if new == old else new


def _plain(v: Any) -> Any:
    """Plain data: mappings as dicts, tuples as lists."""
    if isinstance(v, Mapping):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def dropped(cfg: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The keys of a legacy configuration that are not migrated, with the reason."""
    return [(k, t.why) for k, _ in _leaves(cfg) if isinstance(t := _CFG_MAP.get(k), Drop)]


def map_config(cfg: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Map a legacy configuration to the units' configuration items.

    Returns:
        ``{unit: item}``; each item holds only what differs from the unit's
        package defaults.

    Raises:
        MigrateError: a key is neither mapped nor dropped, or a result
            doesn't validate.
    """
    leaves = _leaves(cfg)
    unknown = [k for k, _ in leaves if k not in _CFG_MAP]
    if unknown:
        raise MigrateError(f"Unmapped legacy config keys: {', '.join(sorted(unknown))}")

    full: dict[str, dict[str, Any]] = {}
    for unit, model in MODELS.items():
        full[unit] = model.model_validate(_plain(defaults(unit))).model_dump()
    base = {u: _plain(c) for u, c in full.items()}
    full = {u: _plain(c) for u, c in full.items()}

    # "pid.load" also sets load_pellet; adj.pellet.pid.load must win
    leaves.sort(key=lambda kv: kv[0].startswith(_OVERRIDES_FIRST))
    for key, value in leaves:
        tgt = _CFG_MAP[key]
        if isinstance(tgt, Drop):
            _logger.debug("Dropped %s: %s", key, tgt.why)
            continue
        for unit, path in tgt:
            _set(full[unit], path, _plain(value))

    res: dict[str, dict[str, Any]] = {}
    for unit, model in MODELS.items():
        item = _diff(full[unit], base[unit])
        item = {} if item is NotGiven else item
        try:
            make_config(unit, model, item)
        except Exception as exc:
            raise MigrateError(f"{unit}: the migrated configuration is invalid: {exc}") from exc
        if item:
            res[unit] = item
    return res


# state

_STATE_PIDS: dict[str, tuple[str, str]] = {
    "p_flow": ("flow", "flow"),
    "p_pump": ("flow", "pump"),
    "p_load": ("pump", "pids.load"),
    "p_buffer": ("pump", "pids.buffer"),
    "p_limit": ("pump", "pids.limit"),
    "pp_load": ("pellet", "pids.p_load"),
    "pp_buffer": ("pellet", "pids.p_buffer"),
}
"""Legacy PID state slot → the unit and field that keep it."""

_STATE_MAP: dict[str, tuple[str, str] | Drop] = {
    "run": ("pump", "run"),
    "scaled_low": ("pump", "scaled_low"),
    "load_last": ("pump", "load_last"),
    "avg_heat": ("pump", "avg_heat"),
    "avg_heat_t": ("pump", "avg_heat_t"),
    # wall-clock time, as the pump unit persists them
    "t_change": ("pump", "t_change"),
    "t_run": ("pump", "t_run"),
    "t_load": ("pump", "t_load"),
    "t_pellet_on": ("pellet", "t_pellet_on"),
    "pellet_on": ("pellet", "pellet_on"),
    "pellet_load": ("pellet", "load"),
    "heat_ok": ("heat_valve", "heat_ok"),
    "last_pwm": Drop("the flow unit keeps its own"),
    "last_load": Drop("the pump unit keeps its own"),
    "last_pump": Drop("unused"),
    "start_p": Drop("unused"),
}


def _pid_state(st: Any, now: float) -> dict[str, Any]:
    res: dict[str, Any] = {"t": now}
    if isinstance(st, Mapping):
        for k in ("i", "e", "setpoint"):
            if (v := st.get(k)) is not None:
                res[k] = v
    return res


def map_state(state: Mapping[str, Any] | None, now: float) -> dict[str, dict[str, Any]]:
    """
    Split the legacy state into the units' state items.

    Args:
        state: The legacy state.
        now: The current wall-clock time; PID timestamps are set to it (the
            legacy ones are monotonic time of a process that is gone).

    Raises:
        MigrateError: an unknown key.
    """
    res: dict[str, dict[str, Any]] = {}
    if not state:
        return res
    unknown = [k for k in state if k not in _STATE_MAP and k not in _STATE_PIDS]
    if unknown:
        raise MigrateError(f"Unmapped legacy state keys: {', '.join(sorted(unknown))}")
    for key, value in state.items():
        if key in _STATE_PIDS:
            unit, path = _STATE_PIDS[key]
            _set(res.setdefault(unit, {}), path, _pid_state(value, now))
            continue
        tgt = _STATE_MAP[key]
        if isinstance(tgt, Drop):
            continue
        unit, path = tgt
        v = value
        if key == "heat_ok" and not isinstance(v, bool):
            # a pending switch-on (its start time): wait again after startup
            _set(res.setdefault(unit, {}), "pending", 0.0)
            v = False
        _set(res.setdefault(unit, {}), path, _plain(v))
    return res


# the whole thing


@dataclass
class Migration:
    """What the migration writes."""

    config: dict[str, dict[str, Any]]
    """``cfg.app.heat.<unit>`` items."""
    state: dict[str, dict[str, Any]]
    """``app.heat.<unit>.state`` items."""

    def items(self) -> dict[Path, Any]:
        """All items, by path."""
        res: dict[Path, Any] = {CFG_PATH / u: v for u, v in self.config.items()}
        res.update({state_path(u): v for u, v in self.state.items()})
        return res

    def dump(self) -> str:
        """The items as YAML."""
        import io  # noqa: PLC0415

        f = io.StringIO()
        yprint({str(p): v for p, v in self.items().items()}, f)
        return f.getvalue()


async def migrate(link: LinkSender, mig: Migration, *, commit: bool) -> list[str]:
    """
    Compare the migration's items with the current ones; write them if ``commit``.

    Returns:
        A line per item that differs: ``+ path`` (new), ``~ path`` (changed).
    """
    diff: list[str] = []
    for path, value in mig.items().items():
        try:
            cur = await link.d_get(path)
        except KeyError:
            diff.append(f"+ {path}")
        else:
            if _plain(cur) == value:
                continue
            diff.append(f"~ {path}")
        if commit:
            await link.d_set(path, value, retain=True, verify=False)
    return diff
