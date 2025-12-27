from __future__ import annotations  # noqa: D100

from moat.lib.micro import const

# bitfields

B_STREAM = const(1)
B_ERROR = const(2)
B_WARNING = const(3)  # external warning (no single integer allowed)
B_WARNING_INTERNAL = const(7)  # internal warning (may contain a naked int)

B_FLAGSTR = " SEW"

# errors

E_UNSPEC = const(-1)
E_NO_STREAM = const(-2)
E_CANCEL = const(-3)
E_NO_CMDS = const(-4)
E_SKIP = const(-5)
E_MUST_STREAM = const(-6)
E_ERROR = const(-7)
E_NO_CMD = const(-11)

# Stream states (separate for in/out)

S_END = const(3)  # terminal Stream=False message has been sent/received
S_NEW = const(4)  # No incoming message yet
S_ON = const(5)  # we're streaming (seen/sent first message)
S_OFF = const(6)  # in: we don't want streaming and signalled NO

# Stream directions

SD_NONE = const(0)
SD_IN = const(1)
SD_OUT = const(2)
SD_BOTH = const(3)

__all__ = [  # noqa:RUF022
    # bitfields
    "B_STREAM",
    "B_ERROR",
    "B_WARNING",
    "B_WARNING_INTERNAL",
    "B_FLAGSTR",
    # errors
    "E_UNSPEC",
    "E_NO_STREAM",
    "E_CANCEL",
    "E_NO_CMDS",
    "E_SKIP",
    "E_MUST_STREAM",
    "E_ERROR",
    "E_NO_CMD",
    # stream states
    "S_END",
    "S_NEW",
    "S_ON",
    "S_OFF",
    # stream directions
    "SD_NONE",
    "SD_IN",
    "SD_OUT",
    "SD_BOTH",
]
