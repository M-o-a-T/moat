"""
Closed-loop helper for the pump core: the simulator with the target,
heat-valve, flow and pump units, for the legacy scenarios.
"""

from __future__ import annotations

from moat.dev.heat.flow import FlowUnit
from moat.dev.heat.heat_valve import HeatValveUnit
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.target import TargetUnit
from moat.lib.path import P

from typing import Any

CM_HEAT = P("home.ass.dyn.switch.heizung.main.cmd")


def pump_loop(
    plant: dict[str, Any], seed: int = 1, start: float = 0, pump: Any = None
) -> ClosedLoop:
    "the simulator with the target, heat-valve, flow and pump units wired up; heating enabled"
    cfg = PlantCfg.from_dict({**plant, "day_offset": start})
    loop = ClosedLoop(cfg=cfg, seed=seed)
    loop.set(CM_HEAT, True)
    loop.add_unit(TargetUnit)
    loop.add_unit(HeatValveUnit)
    loop.add_unit(FlowUnit)
    loop.add_unit(PumpUnit, pump)
    return loop
