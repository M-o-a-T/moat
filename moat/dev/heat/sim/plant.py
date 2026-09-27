"""The complete plant: all components wired together."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random

from ._util import C_WATER, kgps
from .buffer import Buffer
from .circuits import Dhw, Heating
from .config import PlantCfg
from .heat_pump import CircPump, HeatPump
from .pellet import Pellet
from .weather import Weather

from typing import Any

__all__ = ["SENSORS", "Energy", "Faults", "Inputs", "Plant"]

SENSORS = (
    "t_in",
    "t_out",
    "r_flow",
    "m_ice",
    "m_power",
    "m_speed",
    "tb_water",
    "tb_heat",
    "tb_mid",
    "tb_low",
    "t_heat",
    "m_air",
    "m_air_pred",
    "m_pellet",
    "m_pellet_state",
    "m_switch",
    "c_heat",
    "c_water",
    "errors",
)
"""Sensor names, as used by the legacy controller where it has one."""

_TEMPS = frozenset((
    "t_in",
    "t_out",
    "tb_water",
    "tb_heat",
    "tb_mid",
    "tb_low",
    "t_heat",
    "m_pellet",
))


@dataclass
class Inputs:
    """Commands to the plant. Field comments name the legacy config entry."""

    hp_mode: int = 0  # cmd.mode.path
    hp_power: float = 0.0  # cmd.power
    pwm: float = 0.0  # output.flow.path
    hp_valve: bool | None = None  # heat-pump loop valve; None: no valve (always open)
    heat_mode: int = 5  # setting.heat.mode.path
    heat_setpoint: float = 40.0  # adj.curve.setting
    water_setpoint: float | None = 50.0  # setting.water; drives the automatic switchover
    switchover: bool | None = None  # force the switchover valve; None: automatic
    pellet_run: bool | None = None  # cmd.pellet.run; None: follow pellet_wanted
    pellet_wanted: bool = False  # cmd.pellet.wanted
    pellet_load: float = 1.0  # cmd.pellet.load
    pellet_temp: float = 65.0  # cmd.pellet.temp
    pellet_patch_goal: float | None = None  # adj.pellet.startup.patch.path


@dataclass
class Faults:
    """Injected faults."""

    stuck: dict[str, Any] = field(default_factory=dict)  # sensor → frozen value
    stale: set[str] = field(default_factory=set)  # sensors that stop updating
    dead_flow_pump: bool = False


@dataclass
class Energy:
    """Energy ledger, kJ, accumulated since the start."""

    hp: float = 0.0  # heat pump, thermal (negative while de-icing)
    hp_el: float = 0.0  # heat pump, electrical
    fire: float = 0.0  # pellet burner
    heating: float = 0.0  # to the heating circuit
    dhw: float = 0.0  # to hot water
    loss: float = 0.0  # to the surroundings

    @property
    def net(self) -> float:
        """Energy that should have been added to the plant's water."""
        return self.hp + self.fire - self.heating - self.dhw - self.loss


class Plant:
    """
    Sans-IO heating plant simulator.

    Set :attr:`inputs`, call :meth:`step`, read :meth:`sensors`. Physics
    is deterministic for a given seed; sensor noise uses a separate
    random stream, so reading sensors does not perturb the physics.
    """

    def __init__(self, cfg: PlantCfg | None = None, *, seed: int = 0, now: float = 0.0) -> None:
        self.cfg = cfg = cfg or PlantCfg()
        self.now = now
        self.inputs = Inputs()
        self.faults = Faults()
        self.ledger = Energy()

        self._rng_phys = Random(seed)
        self._rng_sensor = Random(seed ^ 0x5EED)

        self.weather = Weather(cfg.weather, self._rng_phys, cfg.day_offset)
        self.weather._update(now)  # noqa: SLF001
        self.buffer = Buffer(cfg.buffer)
        self.pump = CircPump(cfg.pump)
        self.hp = HeatPump(cfg.heat_pump, self.buffer.temp(cfg.buffer.hp_out))
        self.pellet = Pellet(cfg.pellet)
        self.heating = Heating(cfg.heating)
        self.dhw = Dhw(cfg.dhw)
        self.switch = False
        self._day = math.floor((now + cfg.day_offset) / 86400)
        self.dhw.add_daily(self._day * 86400, cfg.day_offset)

        self._lag = {"t_in": self.hp.t_in, "t_out": self.hp.t_out}  # thermometer readings
        self._errors: dict[str, int] = {}
        self._blocking: set[str] = set()
        self._published: dict[str, tuple[Any, float]] = {}
        self.energy0 = self.energy

    # physics

    @property
    def energy(self) -> float:
        """Energy stored in the plant's water, kJ relative to 0 °C."""
        return self.buffer.energy + self.hp.energy + self.pellet.energy

    def step(self, dt: float) -> None:
        """Advance the simulation by ``dt`` seconds."""
        cfg = self.cfg
        max_dt = min(cfg.max_dt, 0.9 * self.buffer.mass / kgps(self._max_flow()))
        n = max(1, math.ceil(dt / max_dt - 1e-9))
        for _ in range(n):
            self._step(dt / n)

    def run(self, duration: float, dt: float = 10, cb: Any = None) -> None:
        """Step for ``duration`` seconds; call ``cb(plant)`` after every step."""
        end = self.now + duration
        while self.now < end - 1e-9:
            self.step(min(dt, end - self.now))
            if cb is not None:
                cb(self)

    def _max_flow(self) -> float:
        cfg = self.cfg
        return max(
            cfg.pump.flow_max,
            cfg.pellet.flow,
            cfg.heating.flow,
            cfg.dhw.primary_max,
        )

    def _step(self, dt: float) -> None:
        cfg = self.cfg
        inp = self.inputs
        buf = self.buffer
        bc = cfg.buffer
        led = self.ledger
        t0 = self.now
        self.now = now = t0 + dt

        day = math.floor((now + cfg.day_offset) / 86400)
        if day != self._day:
            self._day = day
            self.dhw.add_daily(day * 86400, cfg.day_offset)

        w = self.weather
        w.step(dt, now)

        # switchover valve
        if inp.switchover is not None:
            self.switch = inp.switchover
        elif inp.water_setpoint is None:
            self.switch = False
        else:
            tw = buf.temp(bc.tap_water)
            if self.switch:
                self.switch = tw < inp.water_setpoint + cfg.switch.hyst_off
            else:
                self.switch = tw < inp.water_setpoint - cfg.switch.hyst_on

        # heat pump loop
        self.hp.blocked = bool(self._blocking)
        flow = self.pump.step(dt, inp.pwm, self.faults.dead_flow_pump or inp.hp_valve is False)
        if inp.hp_valve is True:
            # some water moves even with the pump off (not seen by the flow meter)
            flow = max(flow, cfg.pump.residual)
        hp_out = buf.layer(bc.hp_out)
        t_sup, e_th, loss = self.hp.step(
            dt,
            now,
            mode=inp.hp_mode,
            load=inp.hp_power,
            flow=flow,
            t_ret=buf.t[hp_out],
            t_air=w.t_air,
            rh=w.rh,
        )
        a = math.exp(-dt / cfg.sensor.tau_pipe) if cfg.sensor.tau_pipe else 0.0
        for k, v in (("t_in", self.hp.t_in), ("t_out", self.hp.t_out)):
            self._lag[k] = v + (self._lag[k] - v) * a
        led.hp += e_th
        led.hp_el += self.hp.p_el * dt
        led.loss += loss
        buf.flow(
            kgps(flow) * dt,
            t_sup,
            buf.layer(bc.hp_in_water if self.switch else bc.hp_in_heat),
            hp_out,
        )

        # pellet loop
        p_out = buf.layer(bc.pellet_out)
        p_flow, t_sup, e_fire, loss = self.pellet.step(
            dt,
            now,
            run=inp.pellet_wanted if inp.pellet_run is None else inp.pellet_run,
            load=inp.pellet_load,
            goal=inp.pellet_temp,
            pump_goal=inp.pellet_patch_goal,
            t_ret=buf.t[p_out],
        )
        led.fire += e_fire
        led.loss += loss
        buf.flow(kgps(p_flow) * dt, t_sup, buf.layer(bc.pellet_in), p_out)

        # heating circuit
        h_out = buf.layer(bc.heat_out)
        t_tap = buf.t[h_out]
        m, t_ret = self.heating.step(
            dt,
            on=inp.heat_mode not in cfg.heating.off_codes,
            setpoint=inp.heat_setpoint,
            t_tap=t_tap,
            t_air=w.t_air,
        )
        led.heating += m * C_WATER * (t_tap - t_ret)
        buf.flow(m, t_ret, buf.layer(bc.heat_in), h_out)

        # hot water
        d_out = buf.layer(bc.dhw_out)
        t_top = buf.t[d_out]
        m, t_ret = self.dhw.step(dt, now, t_top)
        led.dhw += m * C_WATER * (t_top - t_ret)
        buf.flow(m, t_ret, buf.layer(bc.dhw_in), d_out)

        led.loss += buf.relax(dt)
        buf.mix()

    # faults

    def inject_error(self, path: str, code: int, block: bool = True) -> None:
        """Report error ``code`` at ``path``; if ``block``, the heat pump refuses to run."""
        self._errors[path] = code
        if block:
            self._blocking.add(path)
        else:
            self._blocking.discard(path)

    def clear_error(self, path: str) -> None:
        """Remove an injected error."""
        self._errors.pop(path, None)
        self._blocking.discard(path)

    def add_dhw(self, start: float, duration: float, lpm: float) -> None:
        """Schedule a hot-water draw."""
        self.dhw.add(start, duration, lpm)

    # sensors

    def truth(self) -> dict[str, Any]:
        """Exact sensor values, without noise, quantisation or faults."""
        buf = self.buffer
        bc = self.cfg.buffer
        return {
            "t_in": self.hp.t_in,
            "t_out": self.hp.t_out,
            "r_flow": self.pump.flow,
            "m_ice": self.hp.stage == "deice",
            "m_power": self.hp.p_el,
            "m_speed": self.hp.speed,
            "tb_water": buf.temp(bc.tap_water),
            "tb_heat": buf.temp(bc.tap_heat),
            "tb_mid": buf.temp(bc.tap_mid),
            "tb_low": buf.temp(bc.tap_low),
            "t_heat": self.heating.t_supply,
            "m_air": self.weather.t_air,
            "m_air_pred": self.weather.forecast_min(self.now),
            "m_pellet": self.pellet.temp,
            "m_pellet_state": self.pellet.code,
            "m_switch": self.switch,
            # the Solvis reports the setpoints it works with
            "c_heat": self.inputs.heat_setpoint,
            "c_water": self.inputs.water_setpoint,
            "errors": {**self.hp.errors, **self._errors},
        }

    def sensors(self) -> dict[str, Any]:
        """Sensor readings: lagged, noisy and quantised, with injected faults."""
        sc = self.cfg.sensor
        rng = self._rng_sensor
        res = {}
        for k, v in {**self.truth(), **self._lag}.items():
            if k in self.faults.stale and k in self._published:
                res[k] = self._published[k][0]
                continue
            if k in self.faults.stuck:
                v = self.faults.stuck[k]  # noqa: PLW2901
            elif k in _TEMPS:
                v = _quant(v + rng.gauss(0, sc.noise), sc.res_temp)  # noqa: PLW2901
            elif k == "r_flow":
                v = _quant(v, sc.res_flow)  # noqa: PLW2901
            elif k == "m_power":
                v = _quant(v, sc.res_power)  # noqa: PLW2901
            elif k in ("m_air", "m_air_pred"):
                v = _quant(v, sc.res_temp)  # noqa: PLW2901
            self._published[k] = (v, self.now)
            res[k] = v
        return res

    def sensor_ts(self, name: str) -> float | None:
        """Time at which sensor ``name`` was last updated by :meth:`sensors`."""
        try:
            return self._published[name][1]
        except KeyError:
            return None


def _quant(v: float, res: float) -> float:
    return round(round(v / res) * res, 6)
