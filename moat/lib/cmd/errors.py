"""
Error classes et al. for moat-lib-cmd.
"""

from __future__ import annotations

from moat.lib.codec.proxy import as_proxy
from .const import *


@as_proxy("_SCmdErr")
class ShortCommandError(ValueError):
    "The command path was too short"

    pass


@as_proxy("_LCmdErr")
class LongCommandError(ValueError):
    "The command path was too long"

    pass


class StreamError(RuntimeError):
    def __new__(cls, msg=()):
        if len(msg) == 1 and isinstance((m := msg[0]), int):
            if m >= 0:
                return Flow(m)
            elif m == E_UNSPEC:
                return super().__new__(StopMe)
            elif m == E_NO_STREAM:
                return super().__new__(NoStream)
            elif m == E_MUST_STREAM:
                return super().__new__(MustStream)
            elif m == E_SKIP:
                return super().__new__(SkippedData)
            elif m == E_NO_CMDS:
                return super().__new__(NoCmds)
            elif m <= E_NO_CMD:
                return super().__new__(NoCmd, E_NO_CMD - m)
        return super().__new__(cls, *msg)

    def __init__(self, msg=()):
        pass


class Flow:
    def __init__(self, n):
        self.n = n


class StopMe(StreamError):
    pass


class SkippedData(StreamError):
    pass


class NoStream(StreamError):
    pass


class NoCmds(StreamError):
    pass


class NoCmd(StreamError):
    pass


class WantsStream(StreamError):
    pass


class MustStream(StreamError):
    pass
