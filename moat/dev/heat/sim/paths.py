"""
Where the plant simulator's sensors and commands live in MoaT-Link.

Native paths (PATHS.md): the units use ``heat.s.*`` and ``temp.*``, not
the ``legacy.`` gateway copies. The closed-loop runner and the
simulator's Link adapter share these maps.
"""

from __future__ import annotations

from moat.lib.path import P

__all__ = ["ERRORS", "INPUT_PATHS", "SENSOR_PATHS"]

SENSOR_PATHS = {
    "t_in": (P("heat.s.pump.temp.in"),),
    "t_out": (P("heat.s.pump.temp.out"),),
    "r_flow": (P("heat.s.pump.flow"),),
    "m_ice": (P("heat.s.pump.de_ice"),),
    "m_power": (P("heat.s.pump.power"),),
    "tb_water": (P("heat.s.buffer.temp.water"),),
    "tb_heat": (P("heat.s.buffer.temp.heat"),),
    "tb_mid": (P("heat.s.buffer.temp.mid"),),
    "tb_low": (P("heat.s.buffer.temp.return"),),
    "t_heat": (P("heat.s.heating.temp.out"),),
    "m_air": (
        P("home.ass.dyn.sensor.temp.garten_kompost_schatten.state"),
        P("temp.avg.temp.aussen_kompost.min"),
    ),
    "m_air_pred": (P("temp.min.forecast:6"),),
    "m_pellet": (P("heat.s.pellets.temp.top"),),
    "m_pellet_state": (P("heat.s.pellets.state"),),
    "m_switch": (P("heat.s.pump.switchover"),),
    "c_heat": (P("heat.s.heat.temp"),),
    "c_water": (P("heat.s.water.temp"),),
}
"""Plant sensor name → the paths it is published at."""

ERRORS = P("heat.s.pump.err")
"""The heat pump's error subtree; each error key is a sub-path."""

INPUT_PATHS = {
    "hp_mode": P("heat.s.pump.cmd.mode"),
    "hp_power": P("heat.s.pump.cmd.power"),
    "pwm": P("heat.s.pump.pid"),
    "hp_valve": P("home.ass.dyn.switch.plug-n5.relay.cmd"),
    "heat_mode": P("heat.s.heat.mode.cmd"),
    "heat_setpoint": P("heat.s.heat.temp.cmd"),
    "pellet_run": P("heat.s.pellets.power.cmd"),
    "pellet_wanted": P("heat.s.pellets.power.cmd.auto"),
    "pellet_load": P("heat.s.pellets.load.goal.cmd"),
    "pellet_temp": P("heat.s.pellets.temp.goal.cmd"),
    "pellet_patch_goal": P("heat.s.pellets.aux:1.goal"),
}
"""Plant input (:class:`~moat.dev.heat.sim.Inputs` field) → the path it is read from."""
