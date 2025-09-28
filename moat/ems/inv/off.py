"""
Inverter mode: turn the thing off
"""

from __future__ import annotations

import anyio
import logging

from . import InvModeBase

logger = logging.getLogger(__name__)

__all__ = ["InvMode_None"]


class InvMode_None(InvModeBase):
    "Set the AC output to zero, then do nothing."

    _mode = 0
    _name = "off"

    @property
    def power(self):
        "The power output(+)/input(-) to set"
        return self.intf.op.get("power", 0)

    _doc = dict(
        power=power.__doc__,
        _l="""\
This module sets the inverter power to a specific value,
defaulting to zero, and then does nothing.

Use this to tell the inverter controller to go out of the way
and disable itself temporarily, e.g. while you're testing some
other program.

The power level is from the point of view of the AC side, i.e.
positive = inverter, negaive = charger.
""",
    )

    async def run(self):
        "do the work"
        intf = self.intf

        logger.info("SET inverter ZERO %.0f", self.power)
        for p in intf.p_set_:
            await p.set_value(-self.power / intf.n_phase)
        await anyio.sleep_forever()
