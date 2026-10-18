"""
Tests for the pump core: transition table, entry actions, start conditions,
OFF rules, timeouts, and the closed loop against the legacy references.
"""

from __future__ import annotations

import pytest
from itertools import pairwise

from moat.dev.heat.config import make_config
from moat.dev.heat.flow import FlowMode
from moat.dev.heat.link import out_path
from moat.dev.heat.pump import (
    PumpCfg,
    PumpCore,
    PumpState,
    PumpTimeout,
    PumpUnit,
    Run,
    TransitionError,
    next_state,
)
from moat.dev.heat.sim.trace import load

from .legacy import trace_file
from .pump_loop import pump_loop

from typing import Any

R = Run
OUT = out_path("pump")


def legacy_next(orun: Run | None, run: Run) -> Run:
    "the legacy validity check and off redirect, verbatim (solvis.py, run_pump)"
    # fmt: off
    if orun == run:
        pass
    elif orun is None:
        pass
    elif run == R.off:
        pass
    elif run == R.ice:
        pass
    elif run.value == orun.value + 1:
        pass
    elif orun != R.off and run == R.down:
        pass
    elif orun == R.off and run == R.down:
        run = R.off
    elif orun == R.down and run == R.off:
        pass
    elif orun == R.ice and run in (R.wait_flow, R.wait_time):
        pass
    else:
        raise ValueError(f"Cannot go from {orun.name} to {run.name}")
    # fmt: on
    if run == R.off and orun not in (R.off, R.wait_time, R.wait_flow, R.wait_power, R.down):
        run = R.down
    return run


@pytest.mark.parametrize("old", [None, *Run])
@pytest.mark.parametrize("new", list(Run))
def test_transition_table(old: Run | None, new: Run) -> None:
    "every state change is allowed, redirected or refused exactly as in the legacy code"
    try:
        want: Run | type[Exception] = legacy_next(old, new)
    except ValueError:
        want = TransitionError
    if want is TransitionError:
        with pytest.raises(TransitionError):
            next_state(old, new)
    else:
        assert next_state(old, new) == want


# single-step tests


def _cfg(**kw: Any) -> PumpCfg:
    return make_config("pump", PumpCfg, kw or None)


DEMAND = {"t_nom": 50, "t_low": 52, "t_adj": 52, "t_set_on": 50, "t_set_off": 51, "source": "heat"}


def _inputs(**kw: Any) -> dict[str, Any]:
    "a cold buffer, idle heat pump, everything allowed"
    res: dict[str, Any] = {
        "t_in": 30.0,
        "t_out": 30.0,
        "r_flow": 0.0,
        "m_ice": False,
        "m_power": 0.0,
        "tb_water": 40.0,
        "tb_heat": 38.0,
        "tb_mid": 36.0,
        "tb_low": 30.0,
        "t_heat": 35.0,
        "c_heat": 45,
        "c_water": 50,
        "target": {"flow_temp": 45.0, "demand": DEMAND},
        "selector": None,
        "pellet": None,
        "errors": None,
        "flow_out": None,
        "passthru": None,
        "rate_cmd": None,
        "override": None,
        "force_start": None,
    }
    res.update(kw)
    return res


class Drive:
    "a pump core and its inputs, stepped by hand"

    def __init__(self, state: PumpState | None = None, **cfg: Any) -> None:
        self.cfg = _cfg(**cfg)
        self.state = state or PumpState()
        self.now = 1000.0
        self.core = PumpCore(self.cfg, self.state, self.now)
        self.inp = _inputs()
        self.out: dict[Any, Any] = {}

    def step(self, dt: float = 10, **kw: Any) -> Any:
        "advance by dt and step the core"
        self.now += dt
        self.inp.update(kw)
        res = self.core.step(dict(self.inp), self.now)
        self.out.update(res.outputs)
        return res

    @property
    def run(self) -> str:
        "the current state"
        return self.out[OUT]["run"]

    @property
    def req(self) -> dict[str, Any]:
        "the current flow request"
        return self.out[self.cfg.flow_request]

    @property
    def power(self) -> float:
        "the power command"
        return self.out[self.cfg.power]

    @property
    def mode(self) -> int:
        "the mode command"
        return self.out[self.cfg.mode]

    def start(self) -> None:
        "cold buffer: off -> ... -> run"
        self.step()
        self.step(r_flow=5.0)
        self.step(m_power=1.5)
        self.step(t_out=35.0)
        assert self.run == "run", self.out[OUT]


def test_restart_from_off_cools_down():
    "restarting with state off goes through down (legacy: orun is None)"
    d = Drive(state=PumpState(run=R.off))
    d.inp.update(tb_heat=55, tb_water=55)  # warm, won't start
    d.step()
    assert d.run == "off"
    assert [e for e in d.state.model_dump()]  # state is usable


def test_start_sequence_and_entry_actions():
    "the start-up states and what each one asks of the heat pump and the flow unit"
    d = Drive()
    d.step()  # off -> wait_time -> (no previous run) wait_flow
    assert d.run == "wait_flow"
    assert d.mode == d.cfg.mode_off
    assert d.req["mode"] == FlowMode.FIXED
    assert d.req["pwm"] == d.cfg.start.init.pwm

    d.step(r_flow=2.0)
    assert d.run == "flow"
    assert d.req["mode"] == FlowMode.RATE
    assert d.req["rate"] == d.cfg.start.init.rate
    assert d.req["preload"] is True

    d.step(r_flow=5.0)  # >= 3/4 of the init rate
    assert d.run == "wait_power"
    assert d.power == d.cfg.start.load
    assert d.mode == d.cfg.mode_on
    assert d.req["rate"] == d.cfg.start.power.rate

    d.step(m_power=1.5)
    assert d.run == "temp"
    assert d.req["mode"] == FlowMode.RATE_TEMP

    d.step(t_out=31.0)  # delta 1 < 2
    assert d.run == "temp"
    d.step(t_out=33.0)
    assert d.run == "run"
    assert d.req["mode"] == FlowMode.TEMP
    assert d.out[OUT]["heat_off"] is False


def test_wait_time_delay():
    "after a run, the next start waits start.delay"
    d = Drive(state=PumpState(t_load=1000.0))
    d.step()
    assert d.run == "wait_time"
    res = d.step(dt=100)
    assert d.run == "wait_time"
    assert res.wake_in is not None
    assert 1000 + d.cfg.start.delay - d.now < res.wake_in < 1000 + d.cfg.start.delay - d.now + 1
    d.step(dt=d.cfg.start.delay)
    assert d.run == "wait_flow"


def test_warm_buffer_stays_off():
    "no start while the buffer is at its target"
    d = Drive()
    d.step(tb_heat=51)
    assert d.run == "off"
    assert d.out[OUT]["reason"] == "warm"
    assert d.power == 0


def test_force_start():
    "force_start skips the temperature check once and is cleared"
    d = Drive()
    d.inp.update(tb_heat=55)
    res = d.step(force_start=True)
    assert d.run == "wait_flow"
    assert res.outputs[d.cfg.force_start] is None


def _running(**cfg: Any) -> Drive:
    d = Drive(**cfg)
    d.start()
    d.inp.update(t_out=40.0, t_in=34.0, r_flow=15.0, m_power=2.0)
    for _ in range(5):
        d.step()
    assert d.run == "run"
    return d


@pytest.mark.parametrize(
    ("name", "setup"),
    [
        ("OFF SCALED", {"tb_heat": 53.0, "scaled_low": 0.01}),
        ("OFF 4", {"tb_heat": 53.0, "tb_mid": 52.0, "t_run": -1000.0}),
        ("OFF 5", {"tb_heat": 53.0, "tb_low": 52.5}),
        ("OFF SCALE PELLET", {"pellet": {"t_pellet_on": True}, "scaled_low": 0.01}),
        (
            "OFF 6",
            {
                "pellet": {"pellet_on": True},
                "target": {"demand": {**DEMAND, "source": "water"}},
                "tb_water": 50.5,
                "tb_heat": 51.0,
            },
        ),
        (
            "OFF 3",
            {
                "pellet": {"pellet_on": True},
                "target": {"demand": {**DEMAND, "source": "water", "t_nom": 55}},
                "tb_water": 52.5,
                "tb_heat": 53.0,
            },
        ),
    ],
)
def test_off_rules(name: str, setup: dict[str, Any]) -> None:
    "each OFF rule, in isolation, stops a run (via down)"
    d = _running()
    st = d.state
    if "scaled_low" in setup:
        st.scaled_low = setup.pop("scaled_low")
    if "t_run" in setup:
        st.t_run = setup.pop("t_run")
    d.step(**setup)
    assert d.run == "down", d.out[OUT]
    assert d.out[OUT]["reason"] == name
    assert d.power == 0
    assert d.mode == d.cfg.mode_off


def test_off_rules_need_warm_buffer():
    "a cold buffer keeps the heat pump running even with a low scaled_low"
    d = _running()
    d.state.scaled_low = 0.01
    d.step()
    assert d.run == "run"


def test_no_power():
    "no power draw for more than no_power seconds ends a run"
    d = _running()
    d.step(m_power=0.1)
    d.step(dt=20)
    assert d.run == "run"
    d.step(dt=20)
    assert d.run == "down"
    assert d.out[OUT]["reason"] == "no power"


def test_down_exit():
    "cool-down ends once t_out - t_in is small"
    d = _running()
    d.step(tb_heat=53.0, tb_low=52.5)
    assert d.run == "down"
    assert d.req["mode"] == FlowMode.RATE_TEMP
    d.step(t_out=36.0, t_in=34.0)
    assert d.run == "off"
    assert d.req["mode"] == FlowMode.OFF


def test_start_timeout():
    "no flow within times.start: abnormal exit"
    d = Drive()
    d.step()
    assert d.run == "wait_flow"
    d.step(dt=d.cfg.times.start - 20)
    with pytest.raises(PumpTimeout):
        d.step(dt=30)


def test_down_timeout():
    "a cool-down that doesn't end: abnormal exit"
    d = _running()
    d.step(tb_heat=53.0, tb_low=52.5)
    assert d.run == "down"
    d.step(dt=d.cfg.times.stop - 20)
    with pytest.raises(PumpTimeout):
        d.step(dt=30)


def test_ice():
    "de-icing interrupts a run; afterwards it restarts or stops depending on the buffer"
    d = _running()
    d.step(m_ice=True)
    assert d.run == "ice"
    assert d.power == 0
    assert d.req["min_pwm"] == d.cfg.de_ice.min_pwm
    assert d.out[d.cfg.feedback_ice] is True
    d.step(m_ice=False)
    assert d.run == "wait_time"

    d = _running()
    d.step(m_ice=True)
    d.step(m_ice=False, tb_mid=52.0)  # buffer warm
    assert d.run == "down"
    assert d.out[OUT]["reason"] == "ice done, buffer warm"


@pytest.mark.parametrize(
    "inp",
    [
        {"override": False},
        {"selector": {"wp": False}},
        {"errors": {"errors": {":2": 123}, "severity": "critical"}},
    ],
)
def test_main_switch(inp: dict[str, Any]) -> None:
    "override, selector and errors stop a run and prevent starting"
    d = _running()
    d.step(**inp)
    assert d.run == "down"
    d.step(t_out=35, t_in=34)
    assert d.run == "off"
    d.step(dt=1000)
    assert d.run == "off"
    assert d.out[d.cfg.feedback_wp] is False


def test_override_true_beats_selector():
    "override True runs the heat pump even if the selector says no"
    d = Drive()
    d.step(selector={"wp": False}, override=True)
    assert d.run == "wait_flow"


BYPASS = {"bypass": True, "switching": None}


def test_passthru():
    "bypassed: no heat-pump commands; the water pump follows the original controller"
    d = _running()
    res = d.step(passthru=BYPASS, rate_cmd=0.7)
    assert d.cfg.power not in res.outputs
    assert d.cfg.mode not in res.outputs
    assert res.outputs[OUT]["reason"] == "passthru"
    assert d.run == "off"
    assert d.req["mode"] == "fixed"
    assert d.req["pwm"] == 0.7
    assert d.step(rate_cmd=1.3).outputs[OUT]["pwm"] == 1.0
    d.step(rate_cmd=None)
    assert d.req["pwm"] == d.cfg.bypass_pwm


def test_passthru_end():
    "after a bypass: cool down, re-sending our commands"
    d = _running()
    d.step(passthru=BYPASS, rate_cmd=0.7)
    res = d.step(passthru={"bypass": False, "switching": None})
    assert d.run == "down"
    assert res.force
    assert res.outputs[d.cfg.power] == 0
    assert res.outputs[d.cfg.mode] == d.cfg.mode_off
    assert d.req["mode"] == "rate_temp"
    assert not d.step().force
    d.step(t_out=34.5, tb_heat=55.0)  # cooled down; the buffer is warm
    assert d.run == "off"


def test_passthru_pending():
    "a pending switch to passthru doesn't stop a running heat pump, but prevents a start"
    pending = {"bypass": False, "switching": "heatpump_idle"}
    d = _running()
    d.step(passthru=pending)
    assert d.run == "run"
    d = Drive()
    d.step(passthru=pending)
    assert d.run == "off"
    assert d.out[OUT]["reason"] == "passthru"
    d.step(passthru={"bypass": False, "switching": None})
    assert d.run != "off"


def test_missing_sensor():
    "without all sensors the core doesn't start"
    d = Drive()
    res = d.step(t_out=None)
    assert d.cfg.power not in res.outputs
    assert "t_out" in res.outputs[OUT]["reason"]


def test_restart_in_run():
    "a restarted core in run restores the last load"
    d = _running()
    for _ in range(30):
        d.step()
    st = PumpState.model_validate(d.state.model_dump())
    assert st.load_last
    d2 = Drive(state=st)
    d2.inp = dict(d.inp)
    d2.now = d.now
    d2.step()
    assert d2.run == "run"


def test_load_limit():
    "the load ramps up with the load average instead of jumping"
    d = _running()
    loads = []
    for _ in range(180):  # 30 min
        d.step(tb_heat=30.0, tb_low=28.0)  # very cold: the PIDs want full load
        loads.append(d.power)
        ll = d.cfg.load_limit
        assert d.power <= max(d.state.avg_load + ll.margin, ll.floor) + 0.02
    assert loads[0] < 0.5
    assert loads[-1] > 0.9
    assert all(b >= a - 1e-9 for a, b in pairwise(loads))


def test_load_limit_floor():
    "the limit doesn't go below its floor, however low the average"
    d = _running()
    d.state.avg_load = 0.0
    d.step(tb_heat=30.0, tb_low=28.0)
    assert d.power == pytest.approx(d.cfg.load_limit.floor, abs=1e-6)

    d = _running(load_limit={"floor": 0.5})
    d.state.avg_load = 0.0
    d.step(tb_heat=30.0, tb_low=28.0)
    assert d.power == pytest.approx(0.5, abs=1e-6)


def test_load_limit_push():
    "raising the goal pushes the load average up"
    d = _running()
    d.state.avg_load = 0.1
    d.step(target={"flow_temp": 50, "demand": {**DEMAND, "t_adj": 55, "t_low": 54}})
    assert d.state.avg_load >= d.cfg.load_limit.push


def test_load_limit_off():
    "tau None disables the limit"
    d = _running(load_limit={"tau": None})
    d.step(tb_heat=30.0, tb_low=28.0)
    d.step(tb_heat=30.0, tb_low=28.0)
    assert d.power == 1


def test_cop():
    "the COP estimate moves towards the measured value"
    d = _running()
    d.state.cop = 3.0
    # 15 l/min, 6 K, 2 kW: 1.16*60*15*6/1000/2 = 3.13
    cops = []
    for _ in range(3000):
        d.step(t_out=40.0, t_in=34.0, r_flow=15.0, m_power=2.0, tb_heat=30.0, tb_low=28.0)
        cops.append(d.state.cop)
    want = 1.16 * 60 * 15 * 6 / 1000 / 2
    assert all(b >= a for a, b in pairwise(cops))
    # legacy gain: 0.0001 * m_power per step
    assert want - d.state.cop == pytest.approx((want - 3.0) * (1 - 0.0002) ** 3000, abs=0.01)


# closed loop


def _metrics(runs: list[tuple[float, str]], end: float) -> dict[str, float]:
    "first start, time spent running, number of runs and of de-ice cycles"
    first = next((t for t, r in runs if r == "run"), None)
    t_run = 0.0
    for (t, r), (t2, _) in zip(runs, [*runs[1:], (end, "")], strict=True):
        if r == "run":
            t_run += t2 - t
    return {
        "first": first,
        "frac": t_run / end,
        "runs": sum(1 for _, r in runs if r == "run"),
        "ice": sum(1 for _, r in runs if r == "ice"),
    }


def _legacy(name: str) -> tuple[dict[str, float], dict[str, Any]]:
    tr = load(trace_file(name).read_text())
    runs = []
    for t, what, val in tr["events"]:
        if what == "run" and (not runs or runs[-1][1] != val):
            runs.append((t, val))
    end = tr["samples"][-1]["t"]
    return _metrics(runs, end), tr["samples"][-1]


SCEN = {
    "cold_start": ({"buffer": {"t_init": (32, 22)}, "weather": {"mean": 2, "amp": 3}}, 10, 6),
    "steady": ({"buffer": {"t_init": (50, 35)}, "weather": {"mean": 6, "amp": 3}}, 8, 12),
    "deice": (
        {
            "buffer": {"t_init": (35, 22)},
            "weather": {"mean": 1.5, "amp": 1, "rh_mean": 0.95, "rh_amp": 0},
        },
        10,
        6,
    ),
}


@pytest.mark.parametrize("name", list(SCEN))
def test_closed_loop_vs_legacy(name: str) -> None:
    "the new core behaves like the legacy controller in the same plant"
    plant, start_h, hours = SCEN[name]
    loop = pump_loop(plant, start=start_h * 3600)
    runs: list[tuple[float, str]] = []

    def cb(lp) -> None:
        r = (lp.get(OUT) or {}).get("run")
        if r and (not runs or runs[-1][1] != r):
            runs.append((lp.now, r))

    loop.run(hours * 3600, 10, cb)
    new = _metrics(runs, hours * 3600)
    old, last = _legacy(name)
    tr = loop.plant.truth()

    assert new["first"] is not None
    assert abs(new["first"] - old["first"]) < 300
    assert new["frac"] == pytest.approx(old["frac"], abs=0.2)
    assert abs(new["ice"] - old["ice"]) <= 1
    assert abs(new["runs"] - old["runs"]) <= max(3, old["runs"] // 2)
    assert tr["tb_water"] == pytest.approx(last["tb_water"], abs=10)
    assert tr["tb_heat"] == pytest.approx(last["tb_heat"], abs=10)


def test_unit_inputs():
    "the adapter watches every input the core reads"
    u = PumpUnit.__new__(PumpUnit)
    u.link = None
    names = set(u.make_inputs(_cfg()))
    # … and the PWM daemon's service, which the adapter turns into a flag
    assert names == set(_inputs()) | {"pwm"}
