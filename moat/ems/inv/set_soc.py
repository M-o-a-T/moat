"""
Inverter mode: go to specific SoC
"""

from __future__ import annotations

import logging

from . import InvModeBase

logger = logging.getLogger(__name__)

__all__ = ["InvMode_SetSOC"]


class InvMode_SetSOC(InvModeBase):
    """Reach a given charge level."""

    _mode = 3
    _name = "soc"

    @property
    def dest_soc(self):
        "The SoC level to aim towards"
        return self.intf.op.get("dest_soc", 0.50)

    @property
    def power_in(self):
        "Power to take from the grid when charging. Positive unless relying on solar."
        return self.intf.op.get("power_in", 0)

    @property
    def power_out(self):
        "Power to send to the grid when discharging. Must be negative."
        return self.intf.op.get("power_out", 0)

    @property
    def excess(self):
        "Additional power to send if available / battery full. -1=unlimited"
        return self.intf.op.get("excess", None)

    _doc = dict(
        power_in=power_in.__doc__,
        power_out=power_out.__doc__,
        dest_soc=dest_soc.__doc__,
        _l="""\
This module tries to charge/discharge the battery towards a given
state of charge (SoC) percentage.

Untested.
""",
    )

    async def run(self):
        "do the work"
        intf = self.intf
        while True:
            ps = intf.calc_grid_p(self.power_in, excess=self.excess)
            await self.set_inv_ps(ps)

            soc = intf.batt_soc
            info = {"now": soc, "dest": self.dest_soc, "delta": soc - self.dest_soc}
            if abs(soc - self.dest_soc) < 0.02:
                info["delta"] = 0
                ps = intf.calc_batt_i(0)
            elif self.dest_soc > soc:  # want power
                info["power"] = self.power_in
                ps = intf.calc_grid_p(self.power_in, excess=self.excess)
            else:  # send power
                info["power"] = self.power_out
                ps = intf.calc_grid_p(self.power_out, excess=self.excess)
            intf.set_state("to_soc", info)
            await self.set_inv_ps(ps)
            await intf.trigger()
