from __future__ import annotations  # noqa: D100

from moat.util.compat import const

# bitfields

B_STREAM = const(1)
B_ERROR = const(2)
B_INITIAL = const(4)  # pseudo flag
B_SENDER = const(8)  # pseudo flag

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
