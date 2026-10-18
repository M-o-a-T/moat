"""
Self-tests of the test harness: closed-loop runner, heat fixture, traces.
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.config import UnitCfg
from moat.dev.heat.link import Override, Reader, out_path
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.paths import INPUT_PATHS, SENSOR_PATHS
from moat.dev.heat.sim.trace import Trace, compare, load
from moat.dev.heat.state import State
from moat.dev.heat.unit import Step, Unit
from moat.lib.path import P, Path

from .conftest import DATA

from typing import Any

TB_WATER = SENSOR_PATHS["tb_water"][0]


class ThermoCfg(UnitCfg):
    "a two-point controller for the buffer top"

    sensor: Path = TB_WATER
    low: float = 45
    high: float = 50
    tick: float | None = 60


class ThermoState(State):
    "on/off"

    on: bool = False


class ThermoCore:
    "runs the heat pump flat out between two temperatures"

    def __init__(self, cfg: ThermoCfg, state: ThermoState) -> None:
        self.cfg = cfg
        self.state = state

    def update_cfg(self, cfg: ThermoCfg) -> None:
        "new config"
        self.cfg = cfg

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        "one step"
        t = inputs["temp"]
        save = False
        if t is not None:
            on = self.state.on
            if on and t > self.cfg.high:
                on = False
            elif not on and t < self.cfg.low:
                on = True
            save = on != self.state.on
            self.state.on = on
        on = self.state.on
        return Step(
            outputs={
                INPUT_PATHS["hp_mode"]: 3 if on else 0,
                INPUT_PATHS["hp_power"]: 1.0 if on else 0.0,
                INPUT_PATHS["pwm"]: 0.4 if on else 0.0,
                out_path("thermo"): {"on": on},
            },
            wake_in=self.cfg.tick,
            save_now=save,
        )


class ThermoUnit(Unit[ThermoCfg, ThermoState]):
    "the adapter"

    name = "thermo"
    cfg_model = ThermoCfg
    state_model = ThermoState

    def make_core(self, cfg: ThermoCfg, state: ThermoState, now: float) -> ThermoCore:  # noqa: ARG002
        "the core"
        return ThermoCore(cfg, state)

    def make_inputs(self, cfg: ThermoCfg) -> dict[str, Reader[Any]]:
        "the buffer top"
        return {"temp": Reader[float](self.link, cfg.sensor)}


COLD = PlantCfg.from_dict({
    "weather": {"mean": 0, "amp": 2},
    "buffer": {"t_init": (40, 25)},
    "dhw": {"daily": ((7, 900, 8), (19, 600, 10))},
})


def _thermo_loop(**cfg: Any) -> tuple[ClosedLoop, Any]:
    loop = ClosedLoop(cfg=COLD, seed=3)
    slot = loop.add_unit(ThermoUnit, cfg or None)
    return loop, slot


def test_closed_loop():
    "a trivial controller closes the loop around the simulator"
    loop, slot = _thermo_loop()
    temps = []
    loop.run(24 * 3600, 10, lambda lp: temps.append(lp.plant.truth()["tb_water"]))

    assert slot.steps > 24 * 60  # timer-driven at least once a minute
    assert slot.saves >= 2
    switched = [v for _, p, v, _ in loop.writes if p == INPUT_PATHS["hp_mode"]]
    assert switched.count(3) >= 2  # it cycled
    late = temps[len(temps) // 4 :]  # after the warm-up
    inside = sum(1 for t in late if 44 <= t <= 55) / len(late)
    assert inside > 0.9  # hot-water draws may pull it below the band for a while
    assert max(late) < 56
    assert loop.plant.ledger.hp > 0


def test_config_item():
    "add_unit merges the config item with the defaults"
    loop, slot = _thermo_loop(low=30, high=35)
    assert slot.cfg.low == 30
    assert slot.cfg.sensor == TB_WATER
    loop.run(12 * 3600)
    assert loop.plant.truth()["tb_water"] < 40


class OvCore:
    "reports its override"

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def update_cfg(self, cfg: Any) -> None:
        "unused"

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        "remember"
        self.seen.append(inputs["ov"])
        return Step()


def test_override_expiry():
    "overrides expire on simulated wall-clock time"
    loop = ClosedLoop(seed=1)
    ov = P("app.heat.override.wp")
    core = OvCore()
    loop.add_core("ov", core, {"ov": Override[bool](None, ov)})  # ty:ignore[invalid-argument-type]
    loop.run(60)
    loop.set(ov, {"value": False, "expires": loop.wall + 300, "reason": "test"})
    loop.run(120)
    assert core.seen[-1] is False
    loop.run(300)
    assert core.seen[-1] is None
    assert core.seen.count(None) == 2  # before, and after expiry; no steps in between


def test_settles_chain():
    "a chain of cores settles within one tick"
    a, b = P("test.a"), P("test.b")

    class Copy:
        def __init__(self, dst: Path) -> None:
            self.dst = dst

        def update_cfg(self, cfg: Any) -> None:
            pass

        def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
            return Step(outputs={self.dst: inputs["x"]})

    loop = ClosedLoop(seed=1)
    loop.add_core("b", Copy(b), {"x": Reader[Any](None, a)})  # ty:ignore[invalid-argument-type]
    loop.add_core("a", Copy(a), {"x": Reader[Any](None, TB_WATER)})  # ty:ignore[invalid-argument-type]
    loop.run(10)
    assert loop.get(b) == loop.get(TB_WATER)


def _thermo_trace() -> Trace:
    loop, _ = _thermo_loop()
    tr = Trace(
        "thermo",
        "two-point controller, cold day",
        paths={"mode": INPUT_PATHS["hp_mode"], "on": out_path("thermo")},
        plant=("tb_water", "tb_low", "t_out"),
        every=600,
    )
    loop.run(12 * 3600, 10, tr.record)
    return tr


def test_trace_reference(trace_check):
    "the closed-loop trace matches its reference"
    trace_check(_thermo_trace().as_dict(), DATA / "closed_loop" / "thermo.json")


def test_trace_compare_detects_deviation(trace_check, tmp_path):
    "a deliberate deviation is reported"
    tr = _thermo_trace()
    ref = load(tr.dump())
    assert compare(ref, load(tr.dump())) == []

    bad = load(tr.dump())
    bad["samples"][10]["tb_water"] += 0.1
    diffs = compare(ref, bad)
    assert len(diffs) == 1
    assert "tb_water" in diffs[0]
    assert compare(ref, bad, tol={"tb_water": 0.2}) == []

    bad = load(tr.dump())
    bad["samples"][5]["mode"] = 99
    assert compare(ref, bad)

    bad = load(tr.dump())
    bad["events"] = [[0, "x", 1]]
    assert compare(ref, bad)

    del bad["samples"][-1]
    assert any("count" in d for d in compare(ref, bad))

    f = tmp_path / "ref.json"
    f.write_text(tr.dump())
    tr.samples[3]["tb_low"] = -1
    with pytest.raises(pytest.fail.Exception, match="difference"):
        trace_check(tr.as_dict(), f)


@pytest.mark.anyio
async def test_heat_scaffold(heat):
    "a unit runs against the test server; the fixture sees its output, state and liveness"
    await heat.seed_config("thermo", {"tick": 0.05})
    h = await heat.run_unit(ThermoUnit)
    await h.wait("alive", bool)

    await heat.feed(TB_WATER, 40.0)
    await h.wait("out", lambda v: v == {"on": True})
    assert await heat.expect(INPUT_PATHS["hp_mode"], lambda v: v == 3) == 3
    await h.wait("state", lambda v: v is not None and v["on"])

    await heat.feed(TB_WATER, 55.0)
    await h.wait("out", lambda v: v == {"on": False})

    h.cancel()
    await anyio.sleep(0.2)
    await heat.feed(TB_WATER, 40.0)
    await anyio.sleep(0.3)
    assert h.out == {"on": False}  # retained, and nobody reacts any more
