"""
This library contains an advanced [PID controller](https://en.wikipedia.org/wiki/Proportional%E2%80%93integral%E2%80%93derivative_controller).

The `PID` class implements a controller with the error term as its input.
The `CPID` version uses a setpoint variable and accepts the
actual system state as its input.

Both variants implement
- timing independence
- a first-order filter on the derivaive term
- wind-up protection
- introspection
- saving and restoring the controller's state

TODO:
- bump-less parameter changes
"""

from __future__ import annotations

from ._impl import CPID as CPID
from ._impl import PID as PID
from ._impl import PID_TC as PID_TC

__all__ = ["CPID", "PID"]
