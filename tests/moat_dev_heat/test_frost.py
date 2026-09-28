"""
Tests for the frost unit (port of ``wp.py``) and its interplay with the
flow unit.
"""

from __future__ import annotations

import pytest
from itertools import pairwise

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.flow import FlowCfg, FlowCore, FlowState
from moat.dev.heat.frost import FrostCfg, FrostCore, FrostState, FrostUnit
from moat.dev.heat.link import out_path
from moat.dev.heat.pellet import PelletUnit
from moat.dev.heat.selector import SelectorUnit
from moat.dev.heat.sim.paths import INPUT_PATHS
from moat.dev.heat.sim.trace import load
from moat.lib.path import P

from .legacy import SCENARIOS, trace_file
from .pump_loop import pump_loop

from typing import Any

OUT = out_path("frost")
VALVE = P("app.heat.ha.valve.cmd")
VALVE_STATE = P("app.heat.ha.valve.state")
PWM = P("heat.s.pump.pid")


class Run:
    "a frost core with inputs that can be changed step by step"

    def __init__(self, item: Any = NotGiven) -> None:
        self.core = FrostCore(make_config("frost", FrostCfg, item), FrostState(), 0)
        self.now = 0.0
        self.inputs: dict[str, Any] = {
            "t_in": 12.0,
            "t_out": 12.0,
            "flow": {"pwm": 0.0, "mode": "off"},
            "valve_state": False,
        }
        self.res: Any = None

    def step(self, dt: float = 1, **kw: Any) -> dict[str, Any]:
        "advance by ``dt`` seconds, with changed inputs"
        self.now += dt
        self.inputs.update(kw)
        self.res = self.core.step(self.inputs, self.now)
        return self.res.outputs[OUT]

    @property
    def valve(self) -> bool:
        "the valve command"
        return self.res.outputs[VALVE]


def test_idle() -> None:
    "warm loop, nobody pumping: valve closed, no pulses"
    r = Run()
    o = r.step()
    assert o["active"] is False
    assert o["pulse"] == 0
    assert r.valve is False
    assert r.res.wake_in is None


def test_cycle() -> None:
    "cold: open the valve and pulse 5 s every 65 s until the loop is warm"
    r = Run()
    r.step()
    o = r.step(t_in=7.9)
    assert o["active"] is True
    assert r.valve is True
    assert o["pulse"] == pytest.approx(1 / 16)
    assert r.res.wake_in == pytest.approx(5)
    r.step(dt=4, valve_state=True)
    assert r.res.outputs[OUT]["pulse"] > 0
    o = r.step(dt=1)
    assert o["pulse"] == 0
    assert r.valve is True
    assert r.res.wake_in == pytest.approx(60)
    o = r.step(dt=60)
    assert o["pulse"] > 0
    o = r.step(dt=5, t_in=9.9)
    assert o["pulse"] == 0
    assert o["active"] is True
    o = r.step(dt=1, t_in=10.0)
    assert o["active"] is False
    assert o["reason"] == "warm"
    assert r.valve is False


def test_edge() -> None:
    "a cycle starts on the way down through t_start, not while it stays cold"
    r = Run()
    r.step(t_in=7.0)  # first reading: cold (as after a restart)
    assert r.res.outputs[OUT]["active"] is True
    r.step(t_in=5.0, valve_state=True)
    r.step(valve_state=False)  # closed by someone
    o = r.step()
    assert o["active"] is False
    assert o["reason"] == "valve closed"
    o = r.step(dt=600, t_in=4.0)
    assert o["active"] is False  # still cold, but no new edge
    r.step(t_in=8.5)
    o = r.step(t_in=7.5)
    assert o["active"] is True


def test_valve_not_yet_open() -> None:
    "the valve's feedback lags: a closed state before it opened doesn't end the cycle"
    r = Run()
    r.step()
    r.step(t_in=7.0, valve_state=False)
    o = r.step(dt=30)
    assert o["active"] is True


def test_external_pump() -> None:
    "someone else runs the pump: the valve opens and closes with it"
    r = Run()
    r.step(flow={"pwm": 0.5, "mode": "rate"})
    assert r.valve is True
    r.step(flow={"pwm": 0.0, "mode": "off"})
    assert r.valve is False


def test_external_pump_ends_cycle() -> None:
    "the pump starts during a cycle: the cycle ends, the valve stays open for it"
    r = Run()
    r.step()
    r.step(t_in=7.0, flow={"pwm": 1 / 16, "mode": "frost"})
    assert r.res.outputs[OUT]["active"] is True
    o = r.step(flow={"pwm": 0.3, "mode": "fixed"})
    assert o["active"] is False
    assert o["reason"] == "pump runs"
    assert r.valve is True
    o = r.step(dt=600, flow={"pwm": 0.0, "mode": "off"})
    assert r.valve is False
    assert o["active"] is False  # no new edge


def test_no_cycle_while_pumping() -> None:
    "no cycle starts while the pump runs anyway"
    r = Run()
    r.step(flow={"pwm": 0.5, "mode": "rate"})
    o = r.step(t_in=7.0)
    assert o["active"] is False
    assert r.valve is True


def test_missing_temperature() -> None:
    "no temperature, nothing happens"
    r = Run()
    o = r.step(t_in=None)
    assert o["active"] is False
    assert o["t_min"] is None


# the flow unit's side


def _flow(**kw: Any) -> tuple[str, float]:
    core = FlowCore(make_config("flow", FlowCfg), FlowState(), 0)
    inputs: dict[str, Any] = {
        "request": {"mode": "off", "seq": 1},
        "override": None,
        "r_flow": 0.0,
        "t_out": 20.0,
        "t_in": 20.0,
        "frost": {"pulse": 1 / 16},
        "pump": {"state": "up"},
    }
    inputs.update(kw)
    res = core.step(inputs, 1)
    o = res.outputs[out_path("flow")]
    assert res.outputs[PWM] == o["pwm"]
    return o["mode"], o["pwm"]


def test_flow_pulse() -> None:
    "the flow unit outputs the pulse while nothing else wants the pump"
    assert _flow() == ("frost", pytest.approx(1 / 16))
    assert _flow(frost={"pulse": 0}) == ("off", 0)
    assert _flow(frost=None) == ("off", 0)
    assert _flow(request={"mode": "fixed", "pwm": 0.4, "seq": 1}) == ("fixed", 0.4)
    assert _flow(override=0.0) == ("override", 0)
    assert _flow(override=0.3) == ("override", 0.3)


# closed loop against the legacy trace


def test_closed_loop_vs_legacy() -> None:
    "a frosty night, heat pump off, pellets heating: cycles like wp.py's"
    sc = SCENARIOS["frost"]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    loop.set(P("app.heat.override.wp"), False)  # legacy: cm_wp off
    loop.add_unit(PelletUnit)
    loop.add_unit(SelectorUnit)  # the frost unit is part of pump_loop
    rows: list[dict[str, Any]] = []

    def cb(lp) -> None:
        # the relay reports its state; a rule drives the burner from its request
        lp.set(VALVE_STATE, lp.get(VALVE))
        lp.set(INPUT_PATHS["pellet_run"], lp.get(P("heat.s.pellets.power.cmd.auto")))
        if round(lp.now) % sc.sample == 0:
            tr = lp.plant.truth()
            rows.append({"valve": bool(lp.get(VALVE)), "t_in": tr["t_in"], "t_out": tr["t_out"]})

    loop.run(sc.duration, sc.dt, cb)
    old = load(trace_file("frost").read_text())["samples"]

    def stats(rs: list[dict[str, Any]]) -> tuple[float, int, float]:
        on = [r["valve"] for r in rs]
        cycles = sum(1 for a, b in pairwise(on) if b and not a)
        return sum(on) / len(on), cycles, min(min(r["t_in"], r["t_out"]) for r in rs)

    frac, cycles, t_min = stats(rows)
    o_frac, o_cycles, o_min = stats(old)
    assert cycles == pytest.approx(o_cycles, abs=2), (cycles, o_cycles)
    assert frac == pytest.approx(o_frac, abs=0.02), (frac, o_frac)
    assert t_min == pytest.approx(o_min, abs=0.5), (t_min, o_min)
    assert t_min > 0


@pytest.mark.anyio
async def test_unit(heat) -> None:
    "the adapter: a cold loop opens the valve and pulses"
    await heat.feed(P("heat.s.pump.temp.in"), 12.0)
    await heat.feed(P("heat.s.pump.temp.out"), 12.0)
    await heat.feed(out_path("flow"), {"pwm": 0.0, "mode": "off"})
    u = await heat.run_unit(FrostUnit)
    await heat.expect(VALVE, lambda v: v is False)
    await heat.feed(P("heat.s.pump.temp.in"), 7.0)
    await heat.expect(VALVE, lambda v: v is True)
    o = await u.wait("out", lambda o: o is not None and o["active"])
    assert o["pulse"] == pytest.approx(1 / 16)
    await heat.feed(P("heat.s.pump.temp.in"), 11.0)
    await heat.feed(P("heat.s.pump.temp.out"), 11.0)
    await heat.expect(VALVE, lambda v: v is False)
