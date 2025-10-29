"""
Random parts
"""

from __future__ import annotations

_attrs = {
    "PID": "pid",
    "Pin": "pin",
    "PWM": "pwm",
    "Relay": "relay",
    "Transfer": "transfer",
}


# Lazy loader, effectively does:
#   global attr
#   from .mod import attr
def __getattr__(attr):
    mod = _attrs.get(attr, None)
    if mod is None:
        raise AttributeError(attr)
    value = getattr(__import__(f"moat.micro.part.{mod}", globals(), None, True, 0), attr)
    globals()[attr] = value
    return value
