"""
Physics sanity tests for the plant simulator.
"""

from __future__ import annotations

import pytest
import time
from itertools import pairwise

from moat.dev.heat.sim import SENSORS, Plant, PlantCfg, Stage
from moat.dev.heat.sim._util import C_WATER


def _codes(p: Plant, duration: float, dt: float = 10) -> list[int]:
    seq = [p.pellet.code]

    def cb(p: Plant) -> None:
        if p.pellet.code != seq[-1]:
            seq.append(p.pellet.code)

    p.run(duration, dt, cb)
    return seq


def _hp_on(p: Plant, load: float = 0.6, pwm: float = 0.5) -> None:
    p.inputs.hp_mode = 3
    p.inputs.hp_power = load
    p.inputs.pwm = pwm


def test_energy_balance():
    "Everything that goes in or out is accounted for."
    p = Plant(seed=3)
    _hp_on(p)
    p.inputs.heat_mode = 3
    p.inputs.heat_setpoint = 45
    p.inputs.pellet_wanted = True
    p.inputs.pellet_load = 0.7
    p.add_dhw(3600, 600, 8)
    p.add_dhw(7 * 3600, 300, 12)
    p.run(6 * 3600)
    p.inputs.pellet_wanted = False
    p.run(6 * 3600)

    led = p.ledger
    assert led.hp > 0
    assert led.fire > 0
    assert led.heating > 0
    assert led.dhw > 0
    assert led.loss > 0
    delta = p.energy - p.energy0
    assert delta == pytest.approx(led.net, rel=1e-6, abs=1)


def test_stratification_stable():
    "A buffer left alone stays stratified and stable, and only loses a little heat."
    p = Plant(seed=1)
    t0 = list(p.buffer.t)
    p.run(12 * 3600, 60)
    t = p.buffer.t
    assert all(a >= b for a, b in pairwise(t))
    assert t[0] - t[-1] > 0.7 * (t0[0] - t0[-1])
    assert t[0] < t0[0]
    assert t[-1] > t0[-1] - 1


def test_mix_inversion():
    "Warm water below cold water mixes, conserving energy."
    p = Plant()
    buf = p.buffer
    buf.t = [30.0] * buf.n
    buf.t[-1] = 60.0
    e0 = buf.energy
    buf.mix()
    assert buf.energy == pytest.approx(e0)
    assert max(buf.t) - min(buf.t) < 1e-9


def test_zero_flow_trips():
    "A running heat pump without flow overheats and trips; it resets once off and cool."
    cfg = PlantCfg()
    p = Plant(cfg, seed=1)
    _hp_on(p, load=0.5, pwm=0)
    p.run(1800, 5)
    s = p.sensors()
    assert p.hp.stage == Stage.trip
    assert s["errors"].get(cfg.heat_pump.trip_path) == cfg.heat_pump.trip_code_out
    assert s["m_power"] < 0.1
    assert s["r_flow"] == 0

    # stays latched while commanded on
    p.inputs.pwm = 0.5
    p.run(1800, 5)
    assert p.hp.stage == Stage.trip

    p.inputs.hp_mode = 0
    p.run(600, 5)
    assert p.hp.stage == Stage.off
    assert not p.sensors()["errors"]


def test_delta_t_matches_power():
    "In steady state, t_out - t_in = P / (c * flow)."
    cfg = PlantCfg.from_dict({"weather": {"sigma": 0, "amp": 0}})
    p = Plant(cfg, seed=1)
    _hp_on(p, load=0.7, pwm=0.6)
    p.run(1800, 5)
    assert p.hp.stage == Stage.run
    hp = p.hp
    flow = p.pump.flow
    expected = hp.p_th / (flow / 60 * C_WATER)
    assert hp.t_out - hp.t_in == pytest.approx(expected, rel=0.05)
    # and it reacts to more flow
    p.inputs.pwm = 0.9
    p.run(600, 5)
    assert hp.t_out - hp.t_in < expected * 0.8


def test_start_sequence():
    "Mode on -> start delay -> run with power; load below minimum means off."
    cfg = PlantCfg()
    p = Plant(cfg, seed=1)
    _hp_on(p, load=0.02)
    p.run(300, 5)
    assert p.hp.stage == Stage.off

    p.inputs.hp_power = 0.1
    p.run(cfg.heat_pump.start_delay / 2, 5)
    assert p.hp.stage == Stage.delay
    assert p.sensors()["m_power"] < 0.5
    p.run(cfg.heat_pump.start_delay, 5)
    assert p.hp.stage == Stage.run
    assert p.sensors()["m_power"] > 1.2  # legacy misc.min_power
    assert p.hp.speed >= cfg.heat_pump.start_speed

    p.run(cfg.heat_pump.warmup + 60, 5)
    assert p.hp.speed == pytest.approx(cfg.heat_pump.min_mod)


def test_deice_cold_humid():
    "De-icing happens when it is cold and humid, and not when it is mild."
    cold = PlantCfg.from_dict({"weather": {"mean": 1, "amp": 1, "rh_mean": 0.95, "rh_amp": 0}})
    p = Plant(cold, seed=2)
    _hp_on(p, load=0.8)
    seen = []

    def cb(p: Plant) -> None:
        if p.sensors()["m_ice"]:
            seen.append(p.now)

    p.run(4 * 3600, 10, cb)
    assert seen
    assert seen[-1] - seen[0] > 3600  # more than one cycle
    assert p.ledger.hp < p.hp.p_max(1) * 0.8 * 4 * 3600  # de-icing costs heat

    mild = PlantCfg.from_dict({"weather": {"mean": 12, "amp": 1, "rh_mean": 0.95, "rh_amp": 0}})
    p = Plant(mild, seed=2)
    _hp_on(p, load=0.8)
    seen.clear()
    p.run(4 * 3600, 10, cb)
    assert not seen


def test_deice_takes_heat():
    "While de-icing the heat pump cools the water."
    p = Plant(seed=1)
    _hp_on(p)
    p.run(600, 5)
    p.hp.ice = 1.0
    p.run(60, 5)
    assert p.hp.stage == Stage.deice
    assert p.sensors()["m_ice"] is True
    assert p.hp.t_out < p.hp.t_in
    p.run(p.cfg.heat_pump.deice_time, 5)
    assert p.hp.stage in (Stage.delay, Stage.run)
    assert p.hp.ice == 0


def test_circulation_pump():
    "Flow is zero at PWM 0, in the dead zone and with the valve closed; it lags; it dies with the pump."
    cfg = PlantCfg()
    p = Plant(cfg, seed=1)
    p.inputs.pwm = 0
    p.run(60, 5)
    assert p.sensors()["r_flow"] == 0
    p.inputs.pwm = cfg.pump.dead
    p.run(60, 5)
    assert p.sensors()["r_flow"] == 0

    p.inputs.pwm = 0.5
    p.step(2)
    f1 = p.pump.flow
    p.run(120, 5)
    f2 = p.pump.flow
    assert 0 < f1 < f2
    assert f2 == pytest.approx(p.pump.target(0.5), rel=1e-3)
    assert p.pump.target(0.25) < p.pump.target(0.5) < p.pump.target(1) == cfg.pump.flow_max

    p.faults.dead_flow_pump = True
    p.step(5)
    assert p.sensors()["r_flow"] == 0

    p.faults.dead_flow_pump = False
    p.inputs.hp_valve = False
    p.run(60, 5)
    assert p.sensors()["r_flow"] == 0
    p.inputs.hp_valve = True
    p.run(60, 5)
    assert p.sensors()["r_flow"] > 0


def test_switchover_charges_top():
    "With the switchover valve set, the heat pump charges the water section."
    cfg = PlantCfg.from_dict({"weather": {"sigma": 0}, "buffer": {"t_init": (30, 20)}})
    res = {}
    for sw in (False, True):
        p = Plant(cfg, seed=1)
        p.inputs.switchover = sw
        _hp_on(p, load=1, pwm=0.3)
        p.run(3600, 10)
        res[sw] = p.sensors()
        assert res[sw]["m_switch"] is sw
    assert res[True]["tb_water"] > res[False]["tb_water"] + 1


def test_switchover_auto():
    "The automatic switchover follows the water setpoint with hysteresis."
    p = Plant(seed=1)
    p.inputs.water_setpoint = 50
    p.step(1)
    assert not p.switch  # top is 55
    p.inputs.water_setpoint = 60
    p.step(1)
    assert p.switch


def test_heating_circuit():
    "Radiators draw from the buffer when on, not in standby; the setpoint limits the supply."
    cfg = PlantCfg.from_dict({"weather": {"sigma": 0, "amp": 0}})
    p = Plant(cfg, seed=1)
    p.inputs.heat_mode = 5
    p.run(3600)
    assert p.ledger.heating == 0
    assert p.heating.t_room < cfg.heating.t_room

    p.inputs.heat_mode = 3
    p.inputs.heat_setpoint = 30
    p.run(3600)
    q30 = p.ledger.heating
    assert q30 > 0
    s = p.sensors()
    assert s["t_heat"] == pytest.approx(30, abs=1)

    p2 = Plant(cfg, seed=1)
    p2.inputs.heat_mode = 3
    p2.inputs.heat_setpoint = 26
    p2.run(3600)
    assert 0 < p2.ledger.heating < q30

    warm = PlantCfg.from_dict({"weather": {"sigma": 0, "amp": 0, "mean": 12}})
    p3 = Plant(warm, seed=1)
    p3.inputs.heat_mode = 3
    p3.inputs.heat_setpoint = 30
    p3.run(3600)
    assert p3.heating.t_room > p.heating.t_room


def test_dhw_draw():
    "A hot-water draw cools the buffer top."
    p = Plant(seed=1)
    p.add_dhw(60, 1200, 12)
    t0 = p.sensors()["tb_water"]
    p.run(60 + 1200)
    assert p.ledger.dhw > 0
    assert p.buffer.t[-1] < 30  # cold return at the bottom
    assert p.sensors()["tb_water"] <= t0

    cfg = PlantCfg.from_dict({"dhw": {"daily": ((7, 300, 10),)}})
    p = Plant(cfg, seed=1)
    p.run(6.9 * 3600, 60)
    assert p.ledger.dhw == 0
    p.run(0.2 * 3600, 60)
    assert p.ledger.dhw > 0


def test_pellet_sequence():
    "The pellet burner walks its state sequence and heats the buffer."
    cfg = PlantCfg()
    c = cfg.pellet.codes
    p = Plant(cfg, seed=1)
    p.inputs.pellet_run = True
    p.inputs.pellet_load = 0.8
    seq = _codes(p, 3600)
    assert seq == [c.off, c.prepare, c.ignite, c.run]
    assert p.sensors()["m_pellet_state"] == c.run
    assert p.pellet.fire == pytest.approx(0.8 * cfg.pellet.p_nom)
    assert p.pellet.pump
    assert p.ledger.fire > 0
    assert p.sensors()["m_pellet"] > 60

    p.inputs.pellet_run = False
    seq = _codes(p, 3600)
    assert seq == [c.run, c.burnout, c.afterrun, c.off]
    assert p.pellet.fire == 0


def test_pellet_standby():
    "A hot boiler burns out and waits in standby, then restarts."
    cfg = PlantCfg.from_dict({"pellet": {"flow": 2}})  # can't get rid of the heat
    c = cfg.pellet.codes
    p = Plant(cfg, seed=1)
    p.inputs.pellet_wanted = True
    p.inputs.pellet_temp = 60
    seq = _codes(p, 3 * 3600)
    assert seq[:7] == [c.off, c.prepare, c.ignite, c.run, c.burnout, c.afterrun, c.standby]


def test_pellet_ignition_failure():
    "Failed ignitions retry, then latch a fault until switched off."
    cfg = PlantCfg()
    c = cfg.pellet.codes
    p = Plant(cfg, seed=1)
    p.pellet.fail_next = 1
    p.inputs.pellet_run = True
    assert _codes(p, 3600) == [c.off, c.prepare, c.ignite, c.prepare, c.ignite, c.run]

    p = Plant(cfg, seed=1)
    p.pellet.fail_next = 5
    p.inputs.pellet_run = True
    assert _codes(p, 3600) == [c.off, c.prepare, c.ignite, c.prepare, c.ignite, c.fault]
    assert p.pellet.fire == 0
    p.inputs.pellet_run = False
    p.step(10)
    assert p.pellet.code == c.off


def test_pellet_patch_goal():
    "The charging pump waits for the startup patch goal."
    p = Plant(seed=1)
    p.inputs.pellet_run = True
    p.inputs.pellet_temp = 90
    p.inputs.pellet_patch_goal = 80
    p.run(1800)
    assert p.pellet.code == p.cfg.pellet.codes.run
    assert not p.pellet.pump
    p.inputs.pellet_patch_goal = 60
    p.step(10)
    assert p.pellet.pump


def test_weather_forecast():
    "The forecast minimum looks ahead; profiles replace the sine."
    cfg = PlantCfg.from_dict({"weather": {"sigma": 0, "mean": 0, "amp": 5, "t_min_hour": 5}})
    p = Plant(cfg, seed=1)  # midnight
    s = p.sensors()
    assert s["m_air_pred"] == pytest.approx(-5, abs=0.1)
    assert s["m_air"] > s["m_air_pred"]

    cfg = PlantCfg.from_dict({"weather": {"sigma": 0, "profile": ((0, 10), (3600, -10))}})
    p = Plant(cfg, seed=1)
    p.run(1800, 60)
    assert p.weather.t_air == pytest.approx(0)
    assert p.sensors()["m_air_pred"] == pytest.approx(-10)


def test_sensor_faults():
    "Stuck sensors report a fixed value, stale ones stop updating."
    p = Plant(seed=1)
    _hp_on(p)
    p.run(600)
    s = p.sensors()
    assert set(s) == set(SENSORS)
    ts = p.sensor_ts("t_out")
    t_out = s["t_out"]

    p.faults.stale.add("t_out")
    p.faults.stuck["tb_low"] = 12.3
    p.run(600)
    s = p.sensors()
    assert s["t_out"] == t_out
    assert p.sensor_ts("t_out") == ts
    assert p.sensor_ts("t_in") == p.now
    assert s["tb_low"] == 12.3


def test_error_injection():
    "An injected blocking error stops the heat pump and shows up in the error sensor."
    p = Plant(seed=1)
    _hp_on(p)
    p.run(600)
    assert p.hp.stage == Stage.run
    p.inject_error(":2", 123)
    p.step(10)
    assert p.hp.stage == Stage.off
    assert p.sensors()["errors"] == {":2": 123}
    p.clear_error(":2")
    p.inject_error("warn", 7, block=False)
    p.run(600)
    assert p.hp.stage == Stage.run
    assert p.sensors()["errors"] == {"warn": 7}


def _trace(seed: int) -> list[dict]:
    p = Plant(seed=seed)
    _hp_on(p)
    p.inputs.heat_mode = 3
    p.inputs.pellet_wanted = True
    res = []
    p.run(4 * 3600, 30, lambda p: res.append(p.sensors()))
    return res


def test_deterministic():
    "Same seed, same trace; different seed, different trace."
    a = _trace(5)
    assert a == _trace(5)
    assert a != _trace(6)


def test_speed():
    "24 simulated hours with all components active run in under two seconds."
    p = Plant(seed=1)
    _hp_on(p)
    p.inputs.heat_mode = 3
    p.inputs.pellet_wanted = True
    p.add_dhw(3600, 600, 10)
    t = time.perf_counter()
    p.run(86400, 10, lambda p: p.sensors())
    assert time.perf_counter() - t < 2


def test_cfg_from_dict():
    "Nested config dicts are accepted; unknown keys are not."
    cfg = PlantCfg.from_dict({"buffer": {"layers": 20}, "max_dt": 5})
    assert cfg.buffer.layers == 20
    assert cfg.buffer.volume == 900
    assert cfg.max_dt == 5
    with pytest.raises(KeyError):
        PlantCfg.from_dict({"buffer": {"nope": 1}})
