"""
Tests for the migration from the legacy controller (HEAT.md §4.1).
"""

from __future__ import annotations

import pytest

from moat.util import attrdict, combine_dict
from moat.dev.heat.config import CFG_PATH, load_config, make_config
from moat.dev.heat.flow import FlowState
from moat.dev.heat.heat_valve import HeatValveState
from moat.dev.heat.pellet import PelletState
from moat.dev.heat.pump import PumpState
from moat.dev.heat.state import state_path
from moat.dev.heat.system.migrate import (
    _CFG_MAP,
    MODELS,
    MigrateError,
    Migration,
    dropped,
    legacy_config,
    map_config,
    map_state,
    migrate,
)
from moat.lib.path import P

from .conftest import DATA

from typing import Any

PROD = (DATA / "solvis.yml").read_text()

STATE: dict[str, Any] = {
    "run": 6,
    "t_change": 1790000000.0,
    "t_run": 1790000000.0,
    "t_load": 1790000100.0,
    "scaled_low": 0.4,
    "load_last": 0.7,
    "avg_heat": 30.5,
    "avg_heat_t": 44.0,
    "t_pellet_on": True,
    "pellet_on": True,
    "pellet_load": 0.6,
    "heat_ok": True,
    "last_pwm": 0.5,
    "last_load": 0.7,
    "start_p": False,
    "p_flow": {"t": 12345.6, "e": 0.5, "i": 0.1, "setpoint": 15},
    "p_pump": {"t": 12345.6, "e": -1.0, "i": 0.2, "setpoint": 55},
    "p_load": {"t": 12345.6, "e": 1.0, "i": 0.3, "setpoint": 50},
    "p_buffer": {"t": 12345.6, "e": 2.0, "i": 0.4, "setpoint": 45},
    "p_limit": {"t": 12345.6, "e": 3.0, "i": 0.5, "setpoint": 57},
    "pp_load": {"t": 12345.6, "e": 4.0, "i": 0.6, "setpoint": 52},
    "pp_buffer": {"t": 12345.6, "e": 5.0, "i": 0.7, "setpoint": 42},
}
NOW = 1_800_000_000.0


def _prod(extra: dict[str, Any]) -> Any:
    "the production config, with changes"
    return combine_dict(extra, legacy_config(PROD), cls=attrdict)


def _full(unit: str, item: dict[str, Any]) -> Any:
    return make_config(unit, MODELS[unit], item)


def test_all_keys_mapped() -> None:
    "production config plus defaults: every key is mapped or dropped"
    cfg = legacy_config(PROD)
    items = map_config(cfg)
    assert set(items) <= set(MODELS)
    # the dropped keys are the documented ones
    keys = {k for k, _ in dropped(cfg)}
    assert {"cmd.bypass.cmd", "cmd.wp", "cmd.pellet.switch", "setting.passthru"} <= keys
    assert "state" in keys
    assert not any(k.startswith("sensor.pump.in") for k in keys)


def test_values() -> None:
    "production values land where the units expect them"
    items = map_config(legacy_config(PROD))
    # the package defaults are the production values
    assert items == {}
    cfg = {u: _full(u, items.get(u, {})) for u in MODELS}
    assert cfg["target"].curve.exp == 1.35
    assert cfg["target"].curve.night.dest == 15
    assert cfg["target"].t_ext == P("temp.avg.temp.aussen_kompost.min")
    assert cfg["pump"].load.i == 0.0015
    assert cfg["pump"].load_pellet is not None
    assert (cfg["pump"].load_pellet.d, cfg["pump"].load_pellet.tf) == (50, 250)
    assert cfg["pump"].load_pellet.p == cfg["pump"].load.p
    assert cfg["pump"].times.start == 500
    assert cfg["pump"].pellet_start.max_low == 50
    assert cfg["flow"].pump.d == -0.2
    assert cfg["flow"].pump.log.value == P("heat.s.pump.pct.pump")
    assert cfg["pellet"].p_load.p == 0.003
    assert cfg["pellet"].adj.max_temp == 75
    assert cfg["heat_valve"].low_pwm == 0.7
    assert cfg["heat_valve"].heat_delta == 12
    assert cfg["selector"].avg_off == -1
    assert cfg["emergency"].stop_delta == 3
    assert cfg["errors"].feed == P("heat.s.pump.err")
    assert cfg["pwm"].outputs["flow"].pin == 4


def test_differs_from_defaults() -> None:
    "values that differ from the package defaults are written"
    cfg = _prod({"misc": {"pellet": {"current": 2}}, "pid": {"flow": {"p": 0.05}}})
    items = map_config(cfg)
    assert items["selector"] == {"current": 2}
    assert items["flow"] == {"flow": {"p": 0.05}}


def test_defaults_only() -> None:
    "the legacy built-in defaults alone differ from production in many places"
    items = map_config(legacy_config())
    assert items["target"]["curve"]["exp"] == 1.3
    assert items["pump"]["load"]["i"] == 0.0005


def test_unknown_key() -> None:
    "a key that is neither mapped nor dropped is an error"
    with pytest.raises(MigrateError, match=r"adj\.frobnicate"):
        map_config(_prod({"adj": {"frobnicate": 3}}))
    with pytest.raises(MigrateError, match=r"pid\.extra\.p"):
        map_config(_prod({"pid": {"extra": {"p": 3}}}))


def test_invalid_value() -> None:
    "a value that doesn't fit the unit's model is an error"
    with pytest.raises(MigrateError, match="target"):
        map_config(_prod({"adj": {"curve": {"dest": "warm"}}}))


def test_map_covers_models() -> None:
    "every mapping target exists in its unit's model"
    cmap: dict[str, Any] = _CFG_MAP
    for key, tgts in cmap.items():
        if not isinstance(tgts, list):
            continue
        for unit, path in tgts:
            d: Any = _full(unit, {}).model_dump()
            for k in path.split("."):
                assert isinstance(d, dict), (key, unit, path)
                assert k in d, (key, unit, path)
                d = d[k]


def test_state() -> None:
    "the state is split per unit; each PID slot lands in its unit"
    st = map_state(STATE, NOW)
    assert set(st) == {"flow", "pump", "pellet", "heat_valve"}
    flow = FlowState.model_validate(st["flow"])
    assert (flow.flow.i, flow.flow.e, flow.flow.setpoint, flow.flow.t) == (0.1, 0.5, 15, NOW)
    assert flow.pump.i == 0.2
    pump = PumpState.model_validate(st["pump"])
    assert pump.run == 6
    assert pump.t_change is None  # monotonic in the unit; not migrated
    assert (pump.scaled_low, pump.load_last, pump.avg_heat, pump.avg_heat_t) == (
        0.4,
        0.7,
        30.5,
        44.0,
    )
    assert [pump.pids.load.i, pump.pids.buffer.i, pump.pids.limit.i] == [0.3, 0.4, 0.5]
    assert pump.pids.load.t == NOW
    pellet = PelletState.model_validate(st["pellet"])
    assert (pellet.t_pellet_on, pellet.pellet_on, pellet.load) == (True, True, 0.6)
    assert [pellet.pids.p_load.i, pellet.pids.p_buffer.i] == [0.6, 0.7]
    assert HeatValveState.model_validate(st["heat_valve"]).heat_ok is True


def test_state_pending() -> None:
    "a pending heating switch-on waits again"
    st = map_state({"heat_ok": 1790000000.0}, NOW)
    hv = HeatValveState.model_validate(st["heat_valve"])
    assert hv.heat_ok is False
    assert hv.pending is not None


def test_state_unknown() -> None:
    "an unknown state key is an error"
    with pytest.raises(MigrateError, match="frob"):
        map_state({**STATE, "frob": 1}, NOW)
    assert map_state(None, NOW) == {}


@pytest.mark.anyio
async def test_round_trip(link) -> None:
    "dry run changes nothing; commit writes items that the units load"
    tweaked = _prod({"misc": {"pellet": {"current": 2}}, "adj": {"curve": {"dest": 22}}})
    mig = Migration(map_config(tweaked), map_state(STATE, NOW))
    assert set(mig.config) == {"selector", "target"}
    diff = await migrate(link, mig, commit=False)
    assert diff
    assert all(d.startswith("+ ") for d in diff)
    with pytest.raises(KeyError):
        await link.d_get(CFG_PATH / "pump")

    diff = await migrate(link, mig, commit=True)
    await link.i_sync()
    assert await migrate(link, mig, commit=False) == []
    for unit, model in MODELS.items():
        cfg = await load_config(link, unit, model)
        assert cfg == _full(unit, mig.config.get(unit, {}))
    assert (await link.d_get(state_path("pump")))["run"] == 6

    # a changed item shows up as such
    unit = next(iter(mig.config))
    await link.d_set(CFG_PATH / unit, {"frob": 1}, retain=True, verify=False)
    await link.i_sync()
    assert await migrate(link, mig, commit=False) == [f"~ {CFG_PATH / unit}"]
    assert "cfg" in mig.dump()


async def test_cli_help(capfd) -> None:
    "``moat dev heat migrate`` exists (running it needs a real MoaT-Link)"
    from moat.src.test import run  # noqa: PLC0415

    await run("dev", "heat", "migrate", "--help", do_stdout=False)
    assert "--commit" in capfd.readouterr().out
