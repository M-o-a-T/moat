"""
Tests for the heat-valve unit (HEAT.md §3.2).
"""

from __future__ import annotations

import pytest
from itertools import pairwise

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.heat_valve import HeatValveCfg, HeatValveCore, HeatValveState, HeatValveUnit
from moat.dev.heat.link import out_path
from moat.dev.heat.sim.paths import INPUT_PATHS
from moat.dev.heat.sim.trace import load
from moat.lib.path import P

from .legacy import SCENARIOS, trace_file
from .pump_loop import pump_loop

from typing import Any

OUT = out_path("heat_valve")
MODE = P("heat.s.heat.mode.cmd")
FB_PUMP = P("app.heat.ha.pump_state")
FB_HEAT = P("app.heat.ha.heat_state")
ON, OFF = 3, 5


def _cfg(item: Any = NotGiven) -> HeatValveCfg:
    return make_config("heat_valve", HeatValveCfg, item)


def _core(item: Any = NotGiven, **state: Any) -> HeatValveCore:
    return HeatValveCore(_cfg(item), HeatValveState(**state), 0)


def _in(run: str = "off", **kw: Any) -> dict[str, Any]:
    "inputs for a warm buffer, heating enabled, pump idle"
    res: dict[str, Any] = {
        "pump": {"run": run, "heat_off": kw.pop("heat_off", False)},
        "flow": {"pwm": kw.pop("pwm", 0.0)},
        "pellet": None,
        "target": {"demand": {"t_adj": kw.pop("t_adj", 45.0)}},
        "tb_heat": 40.0,
        "tb_low": 25.0,
        "t_out": 30.0,
        "m_switch": False,
        "c_heat": 35,
        "cm_heat": True,
    }
    res.update(kw)
    return res


def _hc(core: HeatValveCore, inputs: dict[str, Any], now: float = 0) -> tuple[int, bool]:
    res = core.step(inputs, now)
    o = res.outputs[OUT]
    assert res.outputs[MODE] == (ON if o["on"] else OFF)
    assert res.outputs[FB_PUMP] is o["on"]
    return o["hc"], o["on"]


# the decision, one case per legacy log_hc branch


@pytest.mark.parametrize(
    ("inputs", "state", "hc", "on"),
    [
        # 1: not ok, switched off
        (_in("off", tb_heat=30.0), {"heat_ok": True}, 9, False),
        (_in("wait_power"), {"heat_ok": True}, 7, False),
        # 2: not ok, but the heat pump runs: stays on
        (_in("run", tb_heat=30.0, t_out=30.0), {"heat_ok": True}, 2, True),
        (_in("run", tb_heat=30.0), {"heat_ok": False, "pending": 0.0}, 2, False),
        # ... unless it's routed to the water buffer
        (_in("run", tb_heat=30.0, m_switch=True), {"heat_ok": True}, 9, False),
        # 3: ok and on
        (_in("off"), {"heat_ok": True}, 3, True),
        # 4: ok, start waiting
        (_in("off"), {}, 4, False),
        # 7: starting up (not temp with a warm return)
        (_in("wait_flow"), {}, 7, False),
        (_in("ice"), {}, 7, False),
        (_in("temp", tb_low=20.0, t_adj=45.0), {}, 7, False),
        # 8: the current state keeps heating off
        (_in("down", heat_off=True), {"heat_ok": True}, 8, False),
        # 9: too cold (blend of buffer and outflow by PWM)
        (_in("off", tb_heat=33.0), {}, 9, False),
        (_in("down", tb_heat=40.0, t_out=30.0, pwm=0.7), {}, 9, False),
        # 12: too cold while running, circuit was off: stays off
        (_in("run", tb_heat=30.0, t_out=30.0), {}, 12, False),
        # 10: temp with a warm return: on at once
        (_in("temp", tb_low=35.0, t_adj=45.0), {}, 10, True),
        # 11: same, heating disabled
        (_in("temp", tb_low=35.0, t_adj=45.0, cm_heat=False), {"heat_ok": True}, 14, False),
        # 13: the pellet burner runs
        (_in("wait_power", pellet={"t_pellet_on": 123.0}), {"heat_ok": True}, 13, True),
        # 14: heating disabled, even while the heat pump runs
        (_in("run", cm_heat=False), {"heat_ok": True}, 14, False),
        # 15: missing input: hold
        (_in("run", pump=None), {"heat_ok": True}, 15, True),
        (_in("off", tb_heat=None), {"heat_ok": True}, 15, True),
        (_in("off", cm_heat=None), {"heat_ok": True}, 15, True),
        (_in("off", cm_heat=None), {}, 15, False),
    ],
)
def test_decision(inputs: dict[str, Any], state: dict[str, Any], hc: int, on: bool) -> None:
    "every branch of the legacy decision"
    assert _hc(_core(**state), inputs) == (hc, on)


def test_blend() -> None:
    "the pre-heat test moves from the buffer to the outflow as the PWM rises"
    # c_heat 35, pre_heat -1: the threshold is 34
    for pwm, t_out, ok in (
        (0, 20.0, True),
        (0.35, 28.0, True),
        (0.35, 27.0, False),
        (1, 34.5, True),
    ):
        hc, _ = _hc(_core(), _in("off", tb_heat=40.0, t_out=t_out, pwm=pwm))
        assert (hc == 4) is ok, (pwm, t_out, hc)


def test_delay() -> None:
    "on after `delay` seconds of ok; not ok in between restarts the wait"
    core = _core()
    res = core.step(_in("off"), 0)
    assert res.outputs[OUT]["hc"] == 4
    assert res.wake_in == 30
    assert res.save
    res = core.step(_in("off"), 20)
    assert res.outputs[OUT]["hc"] == 6
    assert res.wake_in == pytest.approx(10)
    assert _hc(core, _in("off", tb_heat=30.0), 25) == (9, False)
    assert core.state.pending is None
    assert _hc(core, _in("off"), 26)[0] == 4
    assert _hc(core, _in("off"), 50)[0] == 6
    res = core.step(_in("off"), 56)
    assert res.outputs[OUT]["on"] is True
    assert res.outputs[OUT]["hc"] == 5
    assert res.save_now
    assert res.wake_in is None


def test_no_switch_off_while_running() -> None:
    "a running heat pump keeps the circuit on until it stops"
    core = _core(heat_ok=True)
    for t in range(10):
        assert _hc(core, _in("run", tb_heat=30.0, t_out=30.0), t) == (2, True)
    assert _hc(core, _in("down", tb_heat=30.0, heat_off=True), 10) == (8, False)


def test_restart_pending() -> None:
    "a pending switch-on waits again after a restart"
    core = HeatValveCore(_cfg(), HeatValveState(pending=-1000.0), 500)
    assert core.state.pending == 500
    assert _hc(core, _in("off"), 510)[0] == 6
    assert _hc(core, _in("off"), 530) == (5, True)


def test_feedback_heat() -> None:
    "cm_heat is echoed"
    core = _core()
    assert core.step(_in(cm_heat=True), 0).outputs[FB_HEAT] is True
    assert core.step(_in(cm_heat=False), 1).outputs[FB_HEAT] is False
    assert FB_HEAT not in core.step(_in(cm_heat=None), 2).outputs


def test_outputs_optional() -> None:
    "outputs can be disabled; the GPIO stand-in"
    core = _core({"mode": None, "feedback_pump": None, "pin": "test.pin"})
    res = core.step(_in("off"), 0)
    assert MODE not in res.outputs
    assert FB_PUMP not in res.outputs
    assert res.outputs[P("test.pin")] == 0.0
    res = core.step(_in("off"), 100)
    assert res.outputs[P("test.pin")] == 1.0


def test_config_reload() -> None:
    "a changed delay applies to a pending switch-on"
    core = _core()
    core.step(_in("off"), 0)
    core.update_cfg(_cfg({"delay": 5}))
    assert _hc(core, _in("off"), 6) == (5, True)


# closed loop against the legacy traces

SCEN = ("cold_start", "steady", "deice", "day_night")


def _legacy(name: str) -> tuple[float, int]:
    samples = load(trace_file(name).read_text())["samples"]
    on = [s["heat_mode"] == ON for s in samples]
    return sum(on) / len(on), sum(1 for a, b in pairwise(on) if b and not a)


@pytest.mark.parametrize("name", SCEN)
def test_closed_loop_vs_legacy(name: str) -> None:
    "the heating circuit runs about as much, and switches about as often, as in the legacy code"
    sc = SCENARIOS[name]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    on: list[bool] = []
    todo = sorted(sc.events)
    paths = {"force_day": P("app.heat.ha.force_day.cmd")}

    def cb(lp) -> None:
        while todo and todo[0][0] <= lp.now:
            _, what, val = todo.pop(0)
            lp.set(paths[what], val)
        if round(lp.now) % sc.sample == 0:
            on.append(lp.get(INPUT_PATHS["heat_mode"]) == ON)

    loop.run(sc.duration, sc.dt, cb)
    frac = sum(on) / len(on)
    starts = sum(1 for a, b in pairwise(on) if b and not a)
    old_frac, old_starts = _legacy(name)
    assert frac == pytest.approx(old_frac, abs=0.1), (frac, old_frac)
    assert abs(starts - old_starts) <= max(2, old_starts // 2), (starts, old_starts)


@pytest.mark.anyio
async def test_unit(heat) -> None:
    "the adapter: waits for the delay, switches on, echoes cm_heat"
    await heat.seed_config("heat_valve", {"delay": 0.3})
    await heat.feed(out_path("pump"), {"run": "off", "heat_off": False})
    await heat.feed(out_path("flow"), {"pwm": 0.0})
    await heat.feed(P("heat.s.buffer.temp.heat"), 40.0)
    await heat.feed(P("heat.s.buffer.temp.return"), 25.0)
    await heat.feed(P("heat.s.pump.temp.out"), 30.0)
    await heat.feed(P("heat.s.heat.temp"), 35)
    await heat.feed(P("app.heat.ha.heat"), True)
    u = await heat.run_unit(HeatValveUnit)
    await heat.expect(MODE, lambda v: v == OFF)
    await heat.expect(FB_HEAT, lambda v: v is True)
    o = await u.wait("out", lambda o: o is not None and o["on"])
    assert o["hc"] == 5
    await heat.expect(MODE, lambda v: v == ON)
    await u.wait("state", lambda s: s is not None and s["heat_ok"] is True)

    await heat.feed(P("app.heat.ha.heat"), False)
    await heat.expect(MODE, lambda v: v == OFF)
    await heat.expect(FB_HEAT, lambda v: v is False)
