"""
Closed-loop scenarios (HEAT.md §5.1, layer 2): unit cores and the plant
simulator in simulated time, compared with the legacy reference traces
where there is one. The safety invariants are checked throughout.
"""

from __future__ import annotations

import pytest
from itertools import pairwise

from moat.dev.heat.errors import ErrorsUnit
from moat.dev.heat.link import out_path
from moat.dev.heat.passthru import IDLE, PassthruUnit, passthru
from moat.dev.heat.pellet import PelletUnit
from moat.dev.heat.pump import PumpTimeout
from moat.dev.heat.selector import PELLET, WP, SelectorUnit
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.paths import INPUT_PATHS
from moat.dev.heat.sim.trace import load
from moat.dev.heat.state import state_path
from moat.dev.heat.target import TargetUnit
from moat.lib.path import P

from .legacy import SCENARIOS, trace_file
from .pump_loop import pump_loop

from typing import Any

PUMP_OUT = out_path("pump")
SEL_OUT = out_path("selector")
TARGET_OUT = out_path("target")
PASSTHRU = state_path("passthru")
REQUEST = P("app.heat.passthru.request")
MODE = INPUT_PATHS["hp_mode"]
POWER_CMD = INPUT_PATHS["hp_power"]
PWM = INPUT_PATHS["pwm"]
RATE = P("heat.s.pump.rate.cmd")
OVR_WP = P("app.heat.override.wp")
HEAT_MODE = INPUT_PATHS["heat_mode"]
VALVE = INPUT_PATHS["hp_valve"]
VALVE_STATE = P("app.heat.ha.valve.state")
WANTED = P("heat.s.pellets.power.cmd.auto")
SET = P("heat.s.heat.temp.cmd")
CM_HEAT = P("app.heat.ha.heat")
C_WATER = P("heat.s.water.temp")
DAY_CMD = P("app.heat.ha.force_day.cmd")
DAY_STATE = P("app.heat.ha.force_day.state")
NIGHT_CMD = P("app.heat.ha.force_night.cmd")
ERR = P("app.modbus.tcp.solvis.502")
HV_ON = 3


# safety invariants


class Invariants:
    """
    The safety invariants (HEAT.md §5.4), checked after every tick:

    - the heat pump never runs while the water doesn't flow,
    - ``t_out`` stays below the heat pump's trip temperature,
    - the water pump runs while ``t_out - t_in`` exceeds ``stop_delta``
      (unless the original controller is in charge),
    - the pump unit doesn't command the heat pump while it is bypassed.

    Brief violations, as sensor lag and start-up cause, are allowed for
    the given grace periods (seconds).
    """

    def __init__(self, stop_delta: float = 3, flow_grace: float = 30, pwm_grace: float = 120):
        self.stop_delta = stop_delta
        self.flow_grace = flow_grace
        self.pwm_grace = pwm_grace
        self._no_flow: float | None = None
        self._no_pwm: float | None = None
        self._seen = 0

    def __call__(self, lp: ClosedLoop) -> None:
        "check, after a tick"
        tr = lp.plant.truth()
        hp = lp.plant.hp
        now = lp.now
        bypassed = passthru(lp.get(PASSTHRU))

        assert hp.stage != "trip", f"t={now}: the heat pump tripped"
        assert tr["t_out"] < lp.plant.cfg.heat_pump.trip_out, f"t={now}: t_out {tr['t_out']:.1f}"

        if hp.stage == "run" and tr["r_flow"] < 0.5:
            if self._no_flow is None:
                self._no_flow = now
            assert now - self._no_flow <= self.flow_grace, f"t={now}: running without flow"
        else:
            self._no_flow = None

        if not bypassed and tr["t_out"] - tr["t_in"] > self.stop_delta and not lp.get(PWM):
            if self._no_pwm is None:
                self._no_pwm = now
            assert now - self._no_pwm <= self.pwm_grace, f"t={now}: hot heat pump, no water pump"
        else:
            self._no_pwm = None

        new, self._seen = lp.writes[self._seen :], len(lp.writes)
        if bypassed:
            bad = [w for w in new if w[3] == "pump" and w[1] in (MODE, POWER_CMD)]
            assert not bad, f"t={now}: pump unit commands a bypassed heat pump: {bad}"


def _with(inv: Invariants, cb: Any = None) -> Any:
    "a closed-loop callback that also checks the invariants"

    def run(lp: ClosedLoop) -> None:
        inv(lp)
        if cb is not None:
            cb(lp)

    return run


# heat pump: start-up, cycling, de-ice


def _metrics(runs: list[tuple[float, str]], end: float) -> dict[str, Any]:
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


def _pump_legacy(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    tr = load(trace_file(name).read_text())
    runs = []
    for t, what, val in tr["events"]:
        if what == "run" and (not runs or runs[-1][1] != val):
            runs.append((t, val))
    end = tr["samples"][-1]["t"]
    return _metrics(runs, end), tr["samples"][-1]


PUMP_SCEN = {
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


@pytest.mark.parametrize("name", list(PUMP_SCEN))
def test_pump_vs_legacy(name: str) -> None:
    "the heat pump starts, runs and de-ices like the legacy controller in the same plant"
    plant, start_h, hours = PUMP_SCEN[name]
    loop = pump_loop(plant, start=start_h * 3600)
    runs: list[tuple[float, str]] = []

    def cb(lp) -> None:
        r = (lp.get(PUMP_OUT) or {}).get("run")
        if r and (not runs or runs[-1][1] != r):
            runs.append((lp.now, r))

    loop.run(hours * 3600, 10, _with(Invariants(), cb))
    new = _metrics(runs, hours * 3600)
    old, last = _pump_legacy(name)
    tr = loop.plant.truth()

    assert new["first"] is not None
    assert abs(new["first"] - old["first"]) < 300
    assert new["frac"] == pytest.approx(old["frac"], abs=0.2)
    assert abs(new["ice"] - old["ice"]) <= 1
    assert abs(new["runs"] - old["runs"]) <= max(3, old["runs"] // 2)
    assert tr["tb_water"] == pytest.approx(last["tb_water"], abs=10)
    assert tr["tb_heat"] == pytest.approx(last["tb_heat"], abs=10)


# heating circuit


def _hv_legacy(name: str) -> tuple[float, int]:
    samples = load(trace_file(name).read_text())["samples"]
    on = [s["heat_mode"] == HV_ON for s in samples]
    return sum(on) / len(on), sum(1 for a, b in pairwise(on) if b and not a)


@pytest.mark.parametrize("name", ["cold_start", "steady", "deice", "day_night"])
def test_heat_valve_vs_legacy(name: str) -> None:
    "the heating circuit runs about as much, and switches about as often, as in the legacy code"
    sc = SCENARIOS[name]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    on: list[bool] = []
    todo = sorted(sc.events)
    paths = {"force_day": DAY_CMD}

    def cb(lp) -> None:
        while todo and todo[0][0] <= lp.now:
            _, what, val = todo.pop(0)
            lp.set(paths[what], val)
        if round(lp.now) % sc.sample == 0:
            on.append(lp.get(HEAT_MODE) == HV_ON)

    loop.run(sc.duration, sc.dt, _with(Invariants(), cb))
    frac = sum(on) / len(on)
    starts = sum(1 for a, b in pairwise(on) if b and not a)
    old_frac, old_starts = _hv_legacy(name)
    assert frac == pytest.approx(old_frac, abs=0.1), (frac, old_frac)
    assert abs(starts - old_starts) <= max(2, old_starts // 2), (starts, old_starts)


# heating curve, day/night


def _target_loop(name: str) -> ClosedLoop:
    sc = SCENARIOS[name]
    loop = ClosedLoop(cfg=PlantCfg.from_dict({**sc.plant, "day_offset": sc.start}), seed=sc.seed)
    loop.set(CM_HEAT, True)
    loop.set(C_WATER, 50)
    loop.add_unit(TargetUnit)
    return loop


def test_flow_temp_override_expiry() -> None:
    "an override of the flow temperature lapses"
    loop = _target_loop("steady")
    loop.run(60)
    ft = loop.get(TARGET_OUT)["flow_temp"]
    loop.set(P("app.heat.override.flow_temp"), {"value": 50.0, "expires": loop.wall + 600})
    loop.run(60)
    assert loop.get(TARGET_OUT)["flow_temp"] == 50
    assert loop.get(SET) == 50
    loop.run(600)
    assert loop.get(TARGET_OUT)["overridden"] is False
    assert loop.get(TARGET_OUT)["flow_temp"] == pytest.approx(ft, abs=1)


def test_day_night_vs_legacy() -> None:
    "the curve setpoint follows the legacy trace: night setback, forced day mode"
    name = "day_night"
    sc = SCENARIOS[name]
    ref = {s["t"]: s["curve"] for s in load(trace_file(name).read_text())["samples"]}
    todo = sorted(sc.events)
    loop = _target_loop(name)
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


# pellet burner


def _pellet_legacy() -> tuple[list[tuple[float, bool]], list[dict[str, Any]]]:
    tr = load(trace_file("pellet_handover").read_text())
    sw: list[tuple[float, bool]] = []
    for s in tr["samples"]:
        w = bool(s["p_wanted"])
        if not sw or sw[-1][1] != w:
            sw.append((s["t"], w))
    return sw, tr["samples"]


def _pellet_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    "load/temp statistics while the burner runs, by heat-pump state"
    wp = [r["load"] for r in rows if r["code"] == 4 and r["run"] == "run"]
    alone = [r["load"] for r in rows if r["code"] == 4 and r["run"] != "run"]
    temps = [r["temp"] for r in rows if r["code"] == 4]
    return {
        "wp_full": sum(1 for x in wp if x >= 0.99) / len(wp) if wp else None,
        "alone": sum(alone) / len(alone) if alone else None,
        "temp": (min(temps), max(temps)) if temps else None,
    }


def test_pellet_vs_legacy():
    "burner load and temperature requests behave as in the legacy pellet_handover run"
    sc = SCENARIOS["pellet_handover"]
    sw, old = _pellet_legacy()
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    loop.add_unit(PelletUnit)
    rows: list[dict[str, Any]] = []
    todo = list(sw)

    def cb(lp) -> None:
        while todo and todo[0][0] <= lp.now:
            _, w = todo.pop(0)
            lp.set(SEL_OUT, {"wp": True, "pellet": w})
            lp.set(INPUT_PATHS["pellet_wanted"], w)
            lp.set(INPUT_PATHS["pellet_run"], w)
        if lp.now % 120 == 0:
            rows.append({
                "t": lp.now,
                "code": lp.get(P("heat.s.pellets.state")),
                "run": (lp.get(PUMP_OUT) or {}).get("run"),
                "load": lp.get(INPUT_PATHS["pellet_load"]),
                "temp": lp.get(INPUT_PATHS["pellet_temp"]),
            })

    loop.run(sc.duration, 10, _with(Invariants(), cb))
    new = _pellet_stats(rows)
    ref = _pellet_stats([
        {"code": s["m_pellet_state"], "run": s["run"], "load": s["p_load"], "temp": s["p_temp"]}
        for s in old
    ])
    assert new["alone"] is not None
    assert ref["alone"] is not None
    assert (
        new["wp_full"] is None or new["wp_full"] > 0.9
    )  # burner at full load beside the heat pump
    assert new["alone"] == pytest.approx(ref["alone"], abs=0.2)
    assert 0.3 <= new["alone"] < 1
    assert ref["temp"][0] - 2 <= new["temp"][0]
    assert new["temp"][1] <= ref["temp"][1] + 3


def test_cold_snap_handover() -> None:
    "frost: the burner takes over without the buffer dropping further, then hands back"
    sc = SCENARIOS["pellet_handover"]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    loop.add_unit(PelletUnit)
    loop.add_unit(SelectorUnit)
    phases: list[tuple[float, Any, Any]] = []
    dip: list[float] = []

    def cb(lp) -> None:
        # in production a rule drives the burner from its request flag
        lp.set(INPUT_PATHS["pellet_run"], lp.get(WANTED))
        o = lp.get(SEL_OUT) or {}
        ph = (o.get("primary"), o.get("phase"))
        if not phases or phases[-1][1:] != ph:
            phases.append((lp.now, *ph))
        if o.get("phase") == "wp_to_pellet":
            dem = (lp.get(TARGET_OUT) or {}).get("demand") or {}
            dip.append(lp.plant.truth()["tb_heat"] - dem["t_low"])

    loop.run(sc.duration, 10, _with(Invariants(), cb))
    seq = [p[1:] for p in phases]
    assert seq[:4] == [
        (WP, "steady"),
        (PELLET, "wp_to_pellet"),
        (PELLET, "steady"),
        (WP, "pellet_to_wp"),
    ], phases
    assert seq[-1] == (WP, "steady"), phases
    # the burner is requested when (and as) the legacy code did
    assert phases[1][0] == pytest.approx(13320, abs=300)
    assert phases[3][0] == pytest.approx(59280, abs=300)
    # the buffer is below t_low when the burner is requested (it is asked
    # for below t_nom); while it comes, the heat pump holds the buffer
    assert dip
    assert min(dip) > dip[0] - 0.5, (dip[0], min(dip))
    assert dip[-1] >= dip[0], (dip[0], dip[-1])


# heat-pump loop frost protection


def test_frost_vs_legacy() -> None:
    "a frosty night, heat pump off, pellets heating: cycles like wp.py's"
    sc = SCENARIOS["frost"]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    loop.set(OVR_WP, False)  # legacy: cm_wp off
    loop.add_unit(PelletUnit)
    loop.add_unit(SelectorUnit)  # the frost unit is part of pump_loop
    rows: list[dict[str, Any]] = []

    def cb(lp) -> None:
        # the relay reports its state; a rule drives the burner from its request
        lp.set(VALVE_STATE, lp.get(VALVE))
        lp.set(INPUT_PATHS["pellet_run"], lp.get(WANTED))
        if round(lp.now) % sc.sample == 0:
            tr = lp.plant.truth()
            rows.append({"valve": bool(lp.get(VALVE)), "t_in": tr["t_in"], "t_out": tr["t_out"]})

    loop.run(sc.duration, sc.dt, _with(Invariants(), cb))
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


# passthru


class PassthruLoop:
    "the simulator with the pump-side units and the passthru unit; test code plays the Solvis"

    def __init__(self) -> None:
        self.loop = pump_loop({})
        self.loop.add_unit(PassthruUnit, {"compr": None, "errors": [ERR]})
        self.solvis: dict[str, Any] | None = None
        """What the Solvis commands while bypassed: mode, power, rate."""
        self.inv = Invariants()

    def get(self, path: P) -> Any:
        "a value on the bus"
        return self.loop.get(path)

    @property
    def state(self) -> dict[str, Any]:
        "the passthru state"
        return self.get(PASSTHRU) or {"bypass": False, "switching": None}

    @property
    def run(self) -> str:
        "the pump unit's state"
        return (self.get(PUMP_OUT) or {}).get("run")

    def cb(self, lp: Any) -> None:
        "the Solvis' commands, while bypassed; the invariants"
        if self.solvis is not None and passthru(lp.get(PASSTHRU)):
            # forwarded via Modbus in reality
            lp.set(MODE, self.solvis["mode"], "solvis")
            lp.set(POWER_CMD, self.solvis["power"], "solvis")
            lp.set(RATE, self.solvis["rate"], "solvis")
        self.inv(lp)

    def until(self, pred: Any, limit: float, dt: float = 10) -> float:
        "run until ``pred()`` holds; return how long that took"
        t0 = self.loop.now
        while not pred():
            assert self.loop.now - t0 < limit, "timeout"
            self.loop.step(dt)
            self.cb(self.loop)
        return self.loop.now - t0

    def writes(self, since: float, *paths: P) -> list[Any]:
        "the cores' writes to @paths since @since"
        return [w for w in self.loop.writes if w[0] >= since and w[1] in paths]


def test_passthru() -> None:
    "a maintenance session with the simulator, then an emergency end"
    lp = PassthruLoop()
    lp.until(lambda: lp.run == "run", 600)

    # requested while the heat pump runs: waits
    lp.loop.set(REQUEST, True)
    lp.until(lambda: lp.state["switching"] == IDLE, 30)
    lp.loop.run(600, 10, lp.cb)
    assert lp.state == {"bypass": False, "switching": IDLE}
    assert lp.run == "run"
    # our heat pump stops (operator), then the switch happens
    lp.loop.set(OVR_WP, False)
    lp.until(lambda: lp.state["bypass"], 1800)
    t_bypass = lp.loop.now
    lp.loop.set(OVR_WP, None)

    # the Solvis runs the heat pump; our water pump follows it
    lp.solvis = {"mode": 3, "power": 0.8, "rate": 0.6}
    lp.until(lambda: (lp.get(P("heat.s.pump.power")) or 0) > 1.5, 600)
    lp.loop.run(1200, 10, lp.cb)
    assert lp.get(PWM) == 0.6
    assert lp.run == "off"
    assert not lp.writes(t_bypass, MODE, POWER_CMD)

    # switching back waits until the Solvis has stopped it
    lp.loop.set(REQUEST, False)
    lp.until(lambda: lp.state["switching"] == IDLE, 30)
    lp.solvis = {"mode": 0, "power": 0, "rate": 0.4}
    lp.until(lambda: not lp.state["bypass"], 1800)
    assert lp.run == "down"
    assert lp.get(MODE) == 0
    assert (lp.get(PWM) or 0) > 0
    lp.until(lambda: lp.run != "down", 1800)

    # again; this time the Solvis poll fails while it runs the heat pump
    lp.loop.set(OVR_WP, False)
    lp.until(lambda: lp.run == "off", 1800)
    lp.loop.set(REQUEST, True)
    lp.until(lambda: lp.state["bypass"], 600)
    lp.loop.set(OVR_WP, None)
    lp.solvis = {"mode": 3, "power": 1.0, "rate": 0.5}
    lp.until(lambda: (lp.get(P("heat.s.pump.power")) or 0) > 1.5, 600)
    lp.loop.run(600, 10, lp.cb)
    lp.loop.set(P("error") + ERR, {"exc": "TimeoutError"})
    lp.loop.step(1)
    assert lp.state == {"bypass": False, "switching": None}
    assert lp.get(REQUEST) is False
    assert lp.run == "down"
    assert lp.get(POWER_CMD) == 0
    assert lp.get(MODE) == 0
    lp.until(lambda: lp.run != "down", 1800)
    tr = lp.loop.plant.truth()
    assert tr["t_out"] - tr["t_in"] < 3


# faults


def _full_loop(name: str) -> ClosedLoop:
    "all units but the watchdog and passthru, with the production rules (see `_rules`)"
    sc = SCENARIOS[name]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    for unit in (PelletUnit, SelectorUnit, ErrorsUnit):
        loop.add_unit(unit)
    return loop


def _rules(lp: ClosedLoop) -> None:
    "what production does outside the units: the burner follows its request, the valve reports"
    lp.set(INPUT_PATHS["pellet_run"], lp.get(WANTED))
    lp.set(VALVE_STATE, lp.get(VALVE))


class Runs:
    "records the pump unit's state changes"

    def __init__(self) -> None:
        self.runs: list[tuple[float, str]] = []

    def __call__(self, lp: ClosedLoop) -> None:
        "record, after a tick"
        r = (lp.get(PUMP_OUT) or {}).get("run")
        if r and (not self.runs or self.runs[-1][1] != r):
            self.runs.append((lp.now, r))

    def first(self, state: str, after: float = 0) -> float:
        "when ``state`` was first entered after ``after``"
        return next(t for t, r in self.runs if r == state and t >= after)

    def during(self, t0: float, t1: float) -> set[str]:
        "the states the pump unit was in between t0 and t1"
        res = {r for t, r in self.runs if t0 <= t < t1}
        before = [r for t, r in self.runs if t < t0]
        if before:
            res.add(before[-1])
        return res


def test_error_mid_run() -> None:
    "a heat-pump error stops it at once; the burner takes over; no restart while it's failed"
    sc = SCENARIOS["error_mid_run"]
    loop = _full_loop("error_mid_run")
    runs = Runs()
    inv = Invariants()

    def cb(lp: ClosedLoop) -> None:
        if lp.now == 2 * 3600:
            lp.plant.inject_error(":2", 123)
        if lp.now == 3 * 3600:
            lp.plant.clear_error(":2")
        _rules(lp)
        runs(lp)
        inv(lp)

    loop.run(sc.duration, sc.dt, cb)
    t_err = 2 * 3600
    assert runs.during(t_err - 600, t_err) & {"run", "ice"}
    assert runs.first("down", t_err) - t_err <= 60
    assert runs.first("off", t_err) - t_err <= 600
    assert runs.during(t_err + 600, 3 * 3600) == {"off"}
    sel = loop.get(SEL_OUT)
    assert sel["primary"] == PELLET
    # the heat pump counts as failed for `retry` (2 h), so it stays off
    assert "run" not in runs.during(3 * 3600, t_err + 7200 - 60)


def test_no_power() -> None:
    "the running heat pump stops drawing power: off, retries, then the start-up timeout"
    sc = SCENARIOS["hp_no_power"]
    loop = pump_loop(sc.plant, seed=sc.seed, start=sc.start)
    runs = Runs()
    inv = Invariants()

    def cb(lp: ClosedLoop) -> None:
        if lp.now == 3600:
            lp.plant.inject_error(":1", 99)  # ignored by the errors unit, as in production
        runs(lp)
        inv(lp)

    with pytest.raises(PumpTimeout):
        loop.run(sc.duration, sc.dt, cb)
    old = [(t, v) for t, what, v in load(trace_file("hp_no_power").read_text())["events"]]
    old_down = next(t for t, v in old if v == "down")
    old_end = next(t for t, v in old if isinstance(v, str) and v.startswith("TimeoutError"))
    assert abs(runs.first("down", 3600) - old_down) <= 60
    assert abs(loop.now - old_end) <= 120, (loop.now, old_end)


def test_ignition_failure() -> None:
    "the burner doesn't ignite: the selector falls back to the heat pump"
    loop = _full_loop("pellet_handover")
    loop.plant.pellet.fail_next = 99  # every ignition fails; the burner latches a fault
    phases: list[tuple[float, Any, Any]] = []
    inv = Invariants()

    def cb(lp: ClosedLoop) -> None:
        _rules(lp)
        o = lp.get(SEL_OUT) or {}
        ph = (o.get("primary"), o.get("phase"))
        if not phases or phases[-1][1:] != ph:
            phases.append((lp.now, *ph))
        inv(lp)

    loop.run(8 * 3600, 10, cb)
    seq = [p[1:] for p in phases]
    assert (PELLET, "wp_to_pellet") in seq, phases
    i = seq.index((PELLET, "wp_to_pellet"))
    assert seq[i + 1] == (WP, "steady"), phases
    # the start timeout (30 min) decides
    assert phases[i + 1][0] - phases[i][0] == pytest.approx(1800, abs=120)
    assert PELLET in loop.get(SEL_OUT)["failed"]
