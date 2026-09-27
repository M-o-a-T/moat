"""
Configuration of the plant simulator.

Units throughout: °C, l/min (flows), kW (power), kJ (energy), kW/K
(conductances), kJ/K (heat capacities), seconds.

The defaults describe a plausible SolvisMax buffer with a SolvisLea air
heat pump and a KWB pellet burner; they are not measured values.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from typing import Any, Self

__all__ = [
    "BufferCfg",
    "DhwCfg",
    "HeatPumpCfg",
    "HeatingCfg",
    "PelletCfg",
    "PelletCodes",
    "PlantCfg",
    "PumpCfg",
    "SensorCfg",
    "SwitchCfg",
    "WeatherCfg",
]


class _Cfg:
    """Mixin: build a (nested) config dataclass from a dict."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None = None) -> Self:
        """Build an instance, recursing into nested config classes."""
        if not data:
            return cls()
        kw = {}
        ftypes = {f.name: f for f in fields(cls)}
        for k, v in data.items():
            if k not in ftypes:
                raise KeyError(f"{cls.__name__}: unknown key {k!r}")
            dflt = getattr(cls(), k)
            if is_dataclass(dflt) and isinstance(v, dict):
                kw[k] = type(dflt).from_dict(v)
            else:
                kw[k] = v
        return cls(**kw)


@dataclass
class BufferCfg(_Cfg):
    """Stratified buffer tank. Heights are fractions from the top (0) to the bottom (1)."""

    volume: float = 900
    layers: int = 12
    ua: float = 0.003  # total loss to the room
    k_cond: float = 0.004  # conduction between adjacent layers
    t_amb: float = 15
    t_init: tuple[float, float] = (55, 25)  # top, bottom; linear in between

    tap_water: float = 0.03  # tb_water
    tap_heat: float = 0.35  # tb_heat
    tap_mid: float = 0.55  # tb_mid
    tap_low: float = 0.95  # tb_low (return)

    hp_in_water: float = 0.0  # heat pump supply while the switchover valve is set
    hp_in_heat: float = 0.35  # heat pump supply otherwise
    hp_out: float = 1.0  # heat pump return
    pellet_in: float = 0.0
    pellet_out: float = 1.0
    heat_out: float = 0.35  # heating circuit supply
    heat_in: float = 1.0  # heating circuit return
    dhw_out: float = 0.0  # fresh-water station primary supply
    dhw_in: float = 1.0


@dataclass
class HeatPumpCfg(_Cfg):
    """Air/water heat pump."""

    p_nom: float = 12  # thermal output at full speed, t_air = t_ref
    t_ref: float = 7
    p_slope: float = 0.025  # relative Pmax change per K of air temperature
    eta: float = 0.45  # fraction of Carnot COP
    cop_min: float = 1.5
    cop_max: float = 8
    lift_hot: float = 3  # condenser above t_out
    lift_cold: float = 5  # evaporator below t_air

    mode_off: int = 0  # cmd.mode value meaning "off"
    min_load: float = 0.04  # commanded load below this means "off"
    min_mod: float = 0.35  # minimum compressor speed while running
    start_speed: float = 0.6  # speed during the start program
    warmup: float = 300
    ramp: float = 0.01  # speed change per second
    start_delay: float = 60  # after mode on, before the compressor starts

    aux: float = 0.15  # electrical draw of fan/controls while running
    standby: float = 0.01

    # The pipes between buffer and heat pump are long and insulated; each is
    # a chain of mixed segments, which gives them some transport latency.
    # Capacities include the pipe itself.
    cap_pipe: float = 30  # supply pipe, buffer → heat pump; t_in at its end
    ua_pipe: float = 0.006
    n_pipe: int = 10
    cap_ret: float = 30  # return pipe, heat pump → buffer
    ua_ret: float = 0.006
    n_ret: int = 10
    outdoor: float = 0.5  # fraction of each pipe that is outside; the rest is at t_room
    t_room: float = 15
    cap_hx: float = 17  # condenser (t_out sensor)
    ua_hx: float = 0.002
    k_bleed: float = 0.03  # conduction between the t_in and t_out ends inside the unit

    trip_out: float = 65  # t_out over-temperature trip
    trip_in: float = 58  # t_in over-temperature trip
    trip_reset: float = 5  # must cool this far below the trip point to reset
    trip_code_out: int = 1101
    trip_code_in: int = 1102
    trip_path: str = "trip"  # error subpath for trips

    ice_t_max: float = 6  # no icing above this air temperature
    ice_t_span: float = 4  # full icing rate this far below ice_t_max
    ice_rh_min: float = 0.6  # no icing below this relative humidity
    ice_time: float = 2700  # s at full speed and worst conditions until de-icing
    deice_time: float = 240
    deice_power: float = 4  # heat taken from the water while de-icing
    deice_el: float = 1.0


@dataclass
class PumpCfg(_Cfg):
    """Heat-pump circulation pump, PWM controlled."""

    flow_max: float = 30
    dead: float = 0.05  # PWM dead zone (the frost task pulses at 1/16, "more than 5%")
    exp: float = 0.8  # flow = flow_max * ((pwm-dead)/(1-dead)) ** exp
    flow_min: float = 2  # minimum flow once the pump runs
    residual: float = 0.6  # flow with the pump off and the loop valve open
    tau: float = 3  # first-order lag


@dataclass
class HeatingCfg(_Cfg):
    """Heating circuit with a mixing valve, radiators, and the house."""

    flow: float = 15
    k_rad: float = 0.08  # radiator output = k_rad * (t_supply - t_room) ** n_rad
    n_rad: float = 1.3
    ua_house: float = 0.25
    cap_house: float = 20000
    t_room: float = 20.5
    sensor_tau: float = 120  # lag of the supply temperature sensor
    off_codes: tuple[int, ...] = (5,)  # setting.heat.mode values meaning "off"


@dataclass
class DhwCfg(_Cfg):
    """Fresh-water station (domestic hot water)."""

    t_hot: float = 45
    t_cold: float = 10
    approach: float = 5  # primary return is this much above t_cold
    min_delta: float = 2  # buffer top must exceed the tap temperature by this
    primary_max: float = 30
    daily: tuple[tuple[float, float, float], ...] = ()  # (hour, duration s, l/min)


@dataclass
class PelletCodes(_Cfg):
    """KWB state codes as interpreted by the legacy controller."""

    off: int = 0
    prepare: int = 11
    ignite: int = 2
    run: int = 4
    standby: int = 30
    burnout: int = 31
    afterrun: int = 32
    fault: int = 44


@dataclass
class PelletCfg(_Cfg):
    """Pellet burner (KWB) with its own boiler water and charging pump."""

    p_nom: float = 15
    min_mod: float = 0.3
    ramp: float = 0.05  # kW per second
    cap: float = 400
    ua: float = 0.02
    t_amb: float = 15
    t_init: float = 20
    flow: float = 20  # charging pump; must carry p_nom at the boiler goal
    pump_on: float = 65  # default charging-pump start temperature
    pump_hyst: float = 3
    pump_min_delta: float = 2  # boiler must be this much warmer than the return

    t_prepare: float = 120
    t_ignite: float = 480
    ignite_retries: int = 1
    t_burnout: float = 600
    t_afterrun: float = 300
    hyst_off: float = 5  # burn out when this far above the goal temperature
    hyst_on: float = 10  # restart from standby when this far below

    codes: PelletCodes = field(default_factory=PelletCodes)


@dataclass
class WeatherCfg(_Cfg):
    """Outside air. Daily sine plus seeded AR(1) noise, or a breakpoint profile."""

    mean: float = 2
    amp: float = 4
    t_min_hour: float = 5
    rh_mean: float = 0.8
    rh_amp: float = 0.1  # humidity peaks when it's coldest
    sigma: float = 0.5
    tau: float = 3600
    # (seconds, temperature) breakpoints; replaces the sine when set
    profile: tuple[tuple[float, float], ...] | None = None
    forecast_horizon: float = 6 * 3600
    forecast_step: float = 900


@dataclass
class SwitchCfg(_Cfg):
    """Automatic switchover valve (Solvis side): heat pump charges the water section."""

    hyst_on: float = 2  # on when tb_water < water_setpoint - hyst_on
    hyst_off: float = 2  # off when tb_water >= water_setpoint + hyst_off


@dataclass
class SensorCfg(_Cfg):
    """Sensor imperfections."""

    noise: float = 0.05  # σ of temperature noise
    tau_pipe: float = 60  # lag of the t_in / t_out thermometers (in wells)
    res_temp: float = 0.1
    res_flow: float = 0.1
    res_power: float = 0.01


@dataclass
class PlantCfg(_Cfg):
    """The whole plant."""

    buffer: BufferCfg = field(default_factory=BufferCfg)
    heat_pump: HeatPumpCfg = field(default_factory=HeatPumpCfg)
    pump: PumpCfg = field(default_factory=PumpCfg)
    heating: HeatingCfg = field(default_factory=HeatingCfg)
    dhw: DhwCfg = field(default_factory=DhwCfg)
    pellet: PelletCfg = field(default_factory=PelletCfg)
    weather: WeatherCfg = field(default_factory=WeatherCfg)
    switch: SwitchCfg = field(default_factory=SwitchCfg)
    sensor: SensorCfg = field(default_factory=SensorCfg)
    max_dt: float = 10  # internal step limit
    day_offset: float = 0  # seconds from local midnight at t=0
