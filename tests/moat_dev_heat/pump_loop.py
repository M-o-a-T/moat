"""
Closed-loop helpers for the pump core: a stand-in for the ``target`` unit
(n84.10 is not done yet) and a runner for the legacy scenarios.
"""

from __future__ import annotations

from moat.dev.heat.flow import FlowUnit
from moat.dev.heat.link import Reader, out_path
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.sim.paths import INPUT_PATHS, SENSOR_PATHS
from moat.dev.heat.unit import Step
from moat.lib.path import P

from typing import Any

T_EXT = P("temp.avg.temp.aussen_kompost.min")


def vt(tau: float, ti: float, max_: float = 72, min_: float = -15, exp: float = 1.35) -> float:
    "the legacy heating curve (production parameters)"
    if tau >= ti:
        return ti
    return ti + (max_ - ti) * pow((ti - tau) / (ti - min_), 1 / exp)


class TargetStub:
    """
    The legacy demand and heating-curve computation (heating enabled, day
    mode), standing in for the target unit.
    """

    def update_cfg(self, cfg: Any) -> None:
        "unused"

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        "demand from the Solvis setpoints; flow temperature from the curve"
        out: dict[Any, Any] = {}
        t_ext = inputs["t_ext"]
        ft = None
        if t_ext is not None:
            ft = vt(t_ext, 21)
            out[INPUT_PATHS["heat_setpoint"]] = int(ft + 0.8)
        cw, ch = inputs["c_water"], inputs["c_heat"]
        if cw is None or ch is None:
            return Step(outputs=out)
        tw_nom, tw_low, tw_adj = cw, cw + 2, cw + 2
        th_nom, th_low, th_adj = ch, ch + 1, ch + 1.5
        out[out_path("target")] = {
            "flow_temp": ft,
            "demand": {
                "t_nom": max(th_nom, tw_nom),
                "t_low": max(th_low, tw_low),
                "t_adj": max(th_adj, tw_adj),
                "t_set_on": max(tw_nom, th_nom),
                "t_set_off": max(tw_nom, th_low),
                "source": "heat",
            },
        }
        return Step(outputs=out)


def pump_loop(
    plant: dict[str, Any], seed: int = 1, start: float = 0, pump: Any = None
) -> ClosedLoop:
    "the simulator with the pump, flow and target stand-in wired up; heating circuit on"
    cfg = PlantCfg.from_dict({**plant, "day_offset": start})
    loop = ClosedLoop(cfg=cfg, seed=seed)
    loop.set(INPUT_PATHS["heat_mode"], 3)
    loop.add_core(
        "target",
        TargetStub(),
        {
            "t_ext": Reader[float](None, T_EXT),  # ty:ignore[invalid-argument-type]
            "c_heat": Reader[float](None, SENSOR_PATHS["c_heat"][0]),  # ty:ignore[invalid-argument-type]
            "c_water": Reader[float](None, SENSOR_PATHS["c_water"][0]),  # ty:ignore[invalid-argument-type]
        },
    )
    loop.add_unit(FlowUnit)
    loop.add_unit(PumpUnit, pump)
    return loop
