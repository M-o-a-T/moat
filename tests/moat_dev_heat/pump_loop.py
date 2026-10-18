"""
Closed-loop helper for the pump core: the simulator with the target,
heat-valve, flow, pump and frost units, for the legacy scenarios.
"""

from __future__ import annotations

from moat.dev.heat.flow import FlowUnit
from moat.dev.heat.frost import FrostUnit
from moat.dev.heat.heat_valve import HeatValveUnit
from moat.dev.heat.link import service_path
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.sim import PlantCfg
from moat.dev.heat.sim.loop import ClosedLoop
from moat.dev.heat.target import TargetUnit
from moat.lib.path import P

from typing import Any

CM_HEAT = P("app.heat.ha.heat")


def pump_loop(
    plant: dict[str, Any], seed: int = 1, start: float = 0, pump: Any = None
) -> ClosedLoop:
    "the simulator with the target, heat-valve, flow, pump and frost units wired up; heating enabled"
    cfg = PlantCfg.from_dict({**plant, "day_offset": start})
    loop = ClosedLoop(cfg=cfg, seed=seed)
    loop.set(CM_HEAT, True)
    # the pump unit's service is up, as in production: the flow unit
    # trusts its requests even when they don't change for a while
    loop.set(service_path("heat", "pump"), {"id": "pump", "up": True})
    loop.add_unit(TargetUnit)
    loop.add_unit(HeatValveUnit)
    loop.add_unit(FlowUnit)
    loop.add_unit(PumpUnit, pump)
    loop.add_unit(FrostUnit)  # also owns the heat-pump loop valve
    return loop
