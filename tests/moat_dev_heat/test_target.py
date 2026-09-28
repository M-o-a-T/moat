"""
Tests for the target unit: heating curve, schedule, force switches,
demand, staleness and override (HEAT.md §3.1).
"""

from __future__ import annotations

import anyio
import pytest
from datetime import datetime, timedelta
from itertools import pairwise

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.link import out_path
from moat.dev.heat.override import path as override_path
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.trace import load
from moat.dev.heat.target import (
    MAX_WAKE,
    CurveCfg,
    TargetCfg,
    TargetCore,
    TargetState,
    TargetUnit,
    curve_table,
    schedule,
    vt,
)
from moat.lib.path import P

from .legacy import SCENARIOS, trace_file

from typing import Any

OUT = out_path("target")
SET = P("heat.s.heat.temp.cmd")
DAY_CMD = P("home.ass.dyn.switch.heizung.day_mode.cmd")
DAY_STATE = P("home.ass.dyn.switch.heizung.day_mode.state")
NIGHT_CMD = P("home.ass.dyn.switch.heizung.night_mode.cmd")
NIGHT_STATE = P("home.ass.dyn.switch.heizung.night_mode.state")
CM_HEAT = P("home.ass.dyn.switch.heizung.main.cmd")
C_WATER = P("heat.s.water.temp")

MON = datetime(2026, 1, 5)  # noqa: DTZ001  # a Monday
NOON = MON.replace(hour=12)


def _cfg(item: Any = NotGiven) -> TargetCfg:
    return make_config("target", TargetCfg, item)


def _core(item: Any = NotGiven) -> TargetCore:
    return TargetCore(_cfg(item), TargetState(), 0)


def _in(**kw: Any) -> dict[str, Any]:
    res: dict[str, Any] = {
        "t_ext": 0.0,
        "c_heat": 40,
        "c_water": 50,
        "cm_heat": True,
        "override": None,
        "force_day": None,
        "force_night": None,
        "local": NOON,
    }
    res.update(kw)
    return res


# the curve


@pytest.mark.parametrize(
    ("tau", "ti", "want"),
    [
        (21, 21, 21),  # tau >= ti: no heating
        (25, 21, 21),
        (15, 15, 15),
        (-15, 21, 72),  # the design point
        (-15, 15, 72),
        (0, 21, 21 + 51 * (21 / 36) ** (1 / 1.35)),
        (10, 21, 21 + 51 * (11 / 36) ** (1 / 1.35)),
        (0, 15, 15 + 57 * (15 / 30) ** (1 / 1.35)),
    ],
)
def test_vt(tau: float, ti: float, want: float) -> None:
    "the legacy curve, production parameters"
    assert vt(tau, ti, CurveCfg()) == pytest.approx(want)


def test_vt_monotonic() -> None:
    "colder outside, warmer flow; day above night"
    rows = curve_table(CurveCfg())
    assert rows[0] == (-15, pytest.approx(72), pytest.approx(72))
    assert rows[-1][0] == 14
    for (_, d1, n1), (_, d2, n2) in pairwise(rows):
        assert d1 > d2
        assert n1 > n2
        assert d2 > n2


# the schedule


def _at(day: int, h: float) -> datetime:
    return MON + timedelta(days=day, hours=h)


@pytest.mark.parametrize(
    ("day", "h", "is_day", "left"),
    [
        (0, 0, False, 5.5),  # Monday
        (0, 5.49, False, 0.01),
        (0, 5.5, True, 16),
        (0, 21.49, True, 0.01),
        (0, 21.5, False, 2.5),
        (3, 21.6, False, 2.4),  # Thursday: weekday stop
        (4, 5.6, True, 23 - 5.6),  # Friday: weekday start ...
        (4, 21.6, True, 23 - 21.6),  # ... but weekend stop
        (4, 23, False, 1),
        (5, 5.6, False, 7 - 5.6),  # Saturday: weekend start ...
        (5, 7, True, 16),  # ... and weekend stop
        (5, 22.9, True, 0.1),
        (6, 6.9, False, 0.1),  # Sunday: weekend start ...
        (6, 21.4, True, 0.1),  # ... but weekday stop
        (6, 21.6, False, 2.4),
    ],
)
def test_schedule(day: int, h: float, is_day: bool, left: float) -> None:
    "weekday/weekend boundaries, including the Friday/Saturday stop quirk"
    d, w = schedule(CurveCfg(), _at(day, h))
    assert d is is_day
    assert w == pytest.approx(left * 3600, abs=1e-3)


def test_night_setback() -> None:
    "day and night room temperatures; wake-up at the next boundary"
    core = _core()
    res = core.step(_in(local=_at(0, 21)), 0)
    assert res.outputs[OUT]["day_active"] is True
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(vt(0, 21, CurveCfg()))
    assert res.wake_in == pytest.approx(1801)
    res = core.step(_in(local=_at(0, 21.5)), 1801)
    assert res.outputs[OUT]["day_active"] is False
    ft = vt(0, 15, CurveCfg())
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(ft)
    assert res.outputs[SET] == int(ft + 0.8)
    assert res.wake_in == pytest.approx(3600 - 1801)  # t_ext's max_age
    res = core.step(_in(local=_at(0, 22), t_ext=1.0), 3600)
    assert res.wake_in == MAX_WAKE  # midnight is further away


def test_no_local_time() -> None:
    "without a clock it's day"
    res = _core().step(_in(local=None), 0)
    assert res.outputs[OUT]["day_active"] is True


# force switches


def test_force() -> None:
    "the force switches override the schedule and exclude each other"
    core = _core()
    night = _at(0, 23)
    res = core.step(_in(local=night, force_day=False, force_night=False), 0)
    assert res.outputs[DAY_STATE] is False
    assert res.outputs[NIGHT_STATE] is False
    assert res.outputs[OUT]["day_active"] is False

    res = core.step(_in(local=night, force_day=True, force_night=False), 1)
    assert res.save
    assert res.outputs[DAY_STATE] is True
    assert res.outputs[NIGHT_STATE] is False
    assert NIGHT_CMD not in res.outputs  # already off
    assert res.outputs[OUT]["day_active"] is True
    assert core.state.locks.day
    assert not core.state.locks.night

    # night: clears day
    res = core.step(_in(local=NOON, force_day=True, force_night=True), 2)
    assert res.outputs[NIGHT_STATE] is True
    assert res.outputs[DAY_CMD] is False
    assert res.outputs[DAY_STATE] is False
    assert res.outputs[OUT]["day_active"] is False
    assert core.state.locks.night
    assert not core.state.locks.day

    # the cleared switch comes back: nothing more happens
    res = core.step(_in(local=NOON, force_day=False, force_night=True), 3)
    assert res.outputs[DAY_STATE] is False
    assert NIGHT_CMD not in res.outputs
    assert res.outputs[OUT]["day_active"] is False

    # off: the schedule applies again
    res = core.step(_in(local=NOON, force_day=False, force_night=False), 4)
    assert res.outputs[NIGHT_STATE] is False
    assert res.outputs[OUT]["day_active"] is True
    assert not core.state.locks.night
    # unchanged switches are not echoed again
    res = core.step(_in(local=NOON, force_day=False, force_night=False), 5)
    assert DAY_STATE not in res.outputs
    assert NIGHT_STATE not in res.outputs
    assert not res.save


def test_force_state_restored() -> None:
    "the locks are persistent"
    st = TargetState.model_validate({"locks": {"night": True}})
    core = TargetCore(_cfg(), st, 0)
    res = core.step(_in(), 0)
    assert res.outputs[OUT]["day_active"] is False


# demand


def test_demand_heat() -> None:
    "heating enabled: the higher of both circuits; t_cur is the heating buffer"
    res = _core().step(_in(c_heat=40, c_water=50, cm_heat=True), 0)
    assert res.outputs[OUT]["demand"] == {
        "t_nom": 50,
        "t_low": 52,
        "t_adj": 52,
        "t_set_on": 50,
        "t_set_off": 50,
        "source": "heat",
    }
    res = _core().step(_in(c_heat=55, c_water=45, cm_heat=True), 0)
    assert res.outputs[OUT]["demand"] == {
        "t_nom": 55,
        "t_low": 56,
        "t_adj": 56.5,
        "t_set_on": 55,
        "t_set_off": 56,
        "source": "heat",
    }


@pytest.mark.parametrize("cm_heat", [False, None])
def test_demand_water(cm_heat: bool | None) -> None:
    "heating off (or unknown): water only"
    res = _core().step(_in(c_heat=55, c_water=45, cm_heat=cm_heat), 0)
    assert res.outputs[OUT]["demand"] == {
        "t_nom": 45,
        "t_low": 47,
        "t_adj": 47,
        "t_set_on": 45,
        "t_set_off": 45,
        "source": "water",
    }


def test_demand_unknown() -> None:
    "no water setpoint, no demand"
    res = _core().step(_in(c_water=None), 0)
    assert res.outputs[OUT]["demand"] is None


# staleness


def test_stale_hold_then_dest() -> None:
    "an unchanging outside temperature is used for max_age + freeze, then dest"
    core = _core({"max_age": 100, "freeze": 50})
    ft = vt(-5, 21, CurveCfg())
    res = core.step(_in(t_ext=-5.0), 0)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(ft)
    assert res.outputs[OUT]["t_ext_stale"] is False
    assert res.wake_in == pytest.approx(100)

    res = core.step(_in(t_ext=-5.0), 120)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(ft)
    assert res.outputs[OUT]["t_ext_stale"] is True
    assert res.wake_in == pytest.approx(30)

    res = core.step(_in(t_ext=-5.0), 150)
    assert res.outputs[OUT]["flow_temp"] == 21
    assert res.outputs[OUT]["t_ext"] is None
    assert res.outputs[SET] == 21

    # a new value: back to normal
    res = core.step(_in(t_ext=-4.0), 160)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(vt(-4, 21, CurveCfg()))
    assert res.outputs[OUT]["t_ext_stale"] is False


def test_stale_deleted() -> None:
    "a deleted outside temperature: its last value is held for freeze"
    core = _core({"max_age": 100, "freeze": 50})
    ft = vt(-5, 21, CurveCfg())
    core.step(_in(t_ext=-5.0), 0)
    res = core.step(_in(t_ext=None), 10)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(ft)
    assert res.outputs[OUT]["t_ext_stale"] is True
    assert res.wake_in == pytest.approx(50)
    res = core.step(_in(t_ext=None), 40)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(ft)
    res = core.step(_in(t_ext=None), 60)
    assert res.outputs[OUT]["flow_temp"] == 21


def test_never_seen() -> None:
    "no outside temperature at all: dest"
    res = _core().step(_in(t_ext=None), 0)
    assert res.outputs[OUT]["flow_temp"] == 21
    assert res.outputs[OUT]["t_ext_stale"] is True


# override


def test_override() -> None:
    "the override replaces the flow temperature; clearing it reverts at once"
    core = _core()
    ft = vt(0, 21, CurveCfg())
    res = core.step(_in(override=45.5), 0)
    o = res.outputs[OUT]
    assert o["flow_temp"] == 45.5
    assert o["flow_temp_computed"] == pytest.approx(ft)
    assert o["overridden"] is True
    assert res.outputs[SET] == 46
    res = core.step(_in(override=None), 10)
    o = res.outputs[OUT]
    assert o["flow_temp"] == pytest.approx(ft)
    assert o["overridden"] is False
    assert res.outputs[SET] == int(ft + 0.8)


def test_config_reload() -> None:
    "a changed configuration applies to the next step"
    core = _core()
    res = core.step(_in(), 0)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(vt(0, 21, CurveCfg()))
    cfg = _cfg({"curve": {"dest": 22, "max": 60}, "setting": None})
    core.update_cfg(cfg)
    res = core.step(_in(), 1)
    assert res.outputs[OUT]["flow_temp"] == pytest.approx(vt(0, 22, cfg.curve))
    assert SET not in res.outputs


# the closed loop


def _loop(name: str) -> ClosedLoop:
    sc = SCENARIOS[name]
    loop = ClosedLoop(cfg=PlantCfg.from_dict({**sc.plant, "day_offset": sc.start}), seed=sc.seed)
    loop.set(CM_HEAT, True)
    loop.set(C_WATER, 50)
    loop.add_unit(TargetUnit)
    return loop


def test_loop_override_expiry() -> None:
    "an override with an expiry time lapses"
    loop = _loop("steady")
    loop.run(60)
    ft = loop.get(OUT)["flow_temp"]
    loop.set(override_path("flow_temp"), {"value": 50.0, "expires": loop.wall + 600})
    loop.run(60)
    assert loop.get(OUT)["flow_temp"] == 50
    assert loop.get(SET) == 50
    loop.run(600)
    assert loop.get(OUT)["overridden"] is False
    assert loop.get(OUT)["flow_temp"] == pytest.approx(ft, abs=1)


def test_loop_vs_legacy() -> None:
    "the curve setpoint follows the legacy trace: night setback, forced day mode"
    name = "day_night"
    sc = SCENARIOS[name]
    ref = {s["t"]: s["curve"] for s in load(trace_file(name).read_text())["samples"]}
    todo = sorted(sc.events)
    loop = _loop(name)
    got: dict[int, Any] = {}
    paths = {"force_day": DAY_CMD, "force_night": NIGHT_CMD}

    def cb(lp: ClosedLoop) -> None:
        while todo and todo[0][0] <= lp.now:
            _, what, val = todo.pop(0)
            lp.set(paths[what], val)
        t = round(lp.now)
        if t % sc.sample == 0:
            got[t] = lp.get(SET)

    loop.run(sc.duration, sc.dt, cb)
    assert set(ref) <= set(got)
    diff = [(t, ref[t], got[t]) for t in sorted(ref) if ref[t] != got[t]]
    # the legacy task notices a schedule boundary only a little later
    bounds = {5.5 * 3600, 21.5 * 3600}
    assert all((t + sc.start) % 86400 in bounds for t, _, _ in diff), diff
    assert len(diff) <= 2, diff
    assert loop.get(DAY_STATE) is False
    days = {t for t in got if t % 3600 == 0 and got[t] > 40}
    assert days, got


@pytest.mark.anyio
async def test_unit(heat) -> None:
    "the adapter: curve, force switch echo, config reload"
    await heat.feed(P("temp.avg.temp.aussen_kompost.min"), 0.0)
    await heat.feed(C_WATER, 50)
    await heat.feed(P("heat.s.heat.temp"), 40)
    await heat.feed(CM_HEAT, True)
    await heat.feed(DAY_CMD, True)
    u = await heat.run_unit(TargetUnit)
    ft = vt(0, 21, CurveCfg())
    o = await u.wait("out", lambda o: o is not None)
    assert o["flow_temp"] == pytest.approx(ft)
    assert o["day_active"] is True
    assert o["demand"]["source"] == "heat"
    await heat.expect(SET, lambda v: v == int(ft + 0.8))
    await heat.expect(DAY_STATE, lambda v: v is True)
    await u.wait("state", lambda s: s is not None and s["locks"]["day"] is True)

    await heat.feed(NIGHT_CMD, True)
    await heat.expect(DAY_CMD, lambda v: v is False)
    await heat.expect(DAY_STATE, lambda v: v is False)
    await heat.expect(NIGHT_STATE, lambda v: v is True)
    o = await u.wait("out", lambda o: o["day_active"] is False)
    assert o["flow_temp"] == pytest.approx(vt(0, 15, CurveCfg()))

    # the day switch again: the night switch, set by someone else, is
    # cleared although the unit has written False there before.
    # (Switch changes are edges: the unit must see its own write come back
    # before the next toggle, or the two coalesce. Operators aren't that fast.)
    await heat.feed(DAY_CMD, True)
    await heat.expect(NIGHT_CMD, lambda v: v is False)
    await anyio.sleep(0.2)
    await heat.feed(NIGHT_CMD, True)
    await heat.expect(DAY_CMD, lambda v: v is False)
    await anyio.sleep(0.2)
    await heat.feed(DAY_CMD, True)
    await heat.expect(NIGHT_CMD, lambda v: v is False)
    await u.wait("out", lambda o: o["day_active"] is True)

    await heat.seed_config("target", {"curve": {"dest": 22}})
    o = await u.wait("out", lambda o: o["flow_temp"] != pytest.approx(ft))
    assert o["flow_temp"] == pytest.approx(vt(0, 22, CurveCfg(dest=22)))


async def test_cli_curve(capfd) -> None:
    "``moat dev heat target curve``"
    from moat.src.test import run  # noqa: PLC0415

    await run("dev", "heat", "target", "curve", "-d", do_stdout=False)
    lines = capfd.readouterr().out.splitlines()
    assert lines[0].split() == ["-15", "72.0", "72.0"]
    assert len(lines) == 30
