"""
Random parts
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

_attrs = {
    "PID": "pid",
    "Pin": "pin",
    "PWM": "pwm",
    "Control": "control",
    "NoOp": "noop",
    "Relay": "relay",
    "Transfer": "transfer",
    "Average": "average",
    "Triac": "triac",
    "MPlex": "mplex",
}


# Lazy loader, effectively does:
#   global attr
#   from .mod import attr
def __getattr__(attr: str) -> Any:
    mod = _attrs.get(attr, None)
    if mod is None:
        raise AttributeError(attr)
    value = getattr(__import__(f"moat.micro.part.{mod}", globals(), None, (attr,), 0), attr)
    globals()[attr] = value
    return value
