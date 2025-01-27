"""
Inverter mode: do nothing (fixed value)
"""

from __future__ import annotations

import logging

from . import InvModeBase

logger = logging.getLogger(__name__)

__all__ = ["InvMode_Idle"]


class InvMode_Idle(InvModeBase):
    "Continuously set AC output to zero (or whatever)."

    _mode = 1
    _name = "idle"

    @property
    def power(self):
        "The power output(+)/input(-) to set"
        return self.intf.op.get("power", 0)

    _doc = dict(
        power=power.__doc__,
        _l="""\
This module continually resets the inverters' output to a specific value,
defaulting to zero.

This module does not care about battery limits! Specifically, it may
discharge the battery below the boundary set by the BMS.

The power level is from the point of view of the AC side, i.e.
positive = inverter, negaive = charger. It is distributed equally
across all phases.
""",
    )

    async def run(self):
        "do the work"
        intf = self.intf

        logger.info("SET inverter IDLE %.0f", self.power)
        while True:
            for p in intf.p_set_:
                await p.set_value(-self.power / intf.n_phase)
            await intf.trigger(20)
