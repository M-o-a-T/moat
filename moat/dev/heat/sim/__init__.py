"""
Plant simulator for the heat controller.

A deterministic, seeded, sans-IO model of the heating plant (buffer,
heat pump, circulation pump, heating circuit, hot water, pellet burner,
weather), advanced by :meth:`Plant.step`. It has no MoaT-Link
dependency; see HEAT.md §5.3.
"""

from __future__ import annotations

from .config import PlantCfg
from .heat_pump import Stage
from .plant import SENSORS, Energy, Faults, Inputs, Plant

__all__ = ["SENSORS", "Energy", "Faults", "Inputs", "Plant", "PlantCfg", "Stage"]
