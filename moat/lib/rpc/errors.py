"""
Error classes et al. for moat-lib-cmd.
"""

from __future__ import annotations

from moat.lib.micro import CancelledError
from moat.lib.proxy import as_proxy

from .const import (
    E_CANCEL,
    E_ERROR,
    E_MUST_STREAM,
    E_NO_CMD,
    E_NO_CMDS,
    E_NO_STREAM,
    E_SKIP,
    E_UNSPEC,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@as_proxy("_NRdyErr")
class NotReadyError(RuntimeError):
    "An element of the command path was not ready"

    pass


@as_proxy("_SCmdErr")
class ShortCommandError(ValueError):
    "The command path was too short"

    pass


@as_proxy("_LCmdErr")
class LongCommandError(ValueError):
    "The command path was too long"

    pass


@as_proxy("_rErr")
class RemoteError(RuntimeError):
    "Some remote error that is not proxied"

    pass


class StreamError(RuntimeError):  # noqa: D101
    def __new__(cls, msg: Sequence[object] = ()):  # noqa: D102
        # Error codes map to fully constructed instances: MicroPython
        # does not call __init__ on them, and refuses to raise an
        # exception whose native base was never initialized.
        if cls is not StreamError or len(msg) != 1:
            pass
        elif isinstance((m := msg[0]), int):
            if m >= 0:
                return Flow(m)
            elif m == E_UNSPEC:
                return StopMe()
            elif m == E_NO_STREAM:
                return NoStream()
            elif m == E_MUST_STREAM:
                return MustStream()
            elif m == E_SKIP:
                return SkippedData()
            elif m == E_NO_CMDS:
                return NoCmds()
            elif m == E_CANCEL:
                return CancelledError()
            elif m == E_ERROR:
                return RemoteError()
            elif m <= E_NO_CMD:
                return NoCmd((E_NO_CMD - m,))
        elif isinstance(m, Exception):
            return m
        return super().__new__(cls)

    def __init__(self, msg=()):
        # CPython calls __init__ again with the original error code
        # when __new__ returned a subclass instance.
        if getattr(self, "_init", False):
            return
        self._init = True
        super().__init__(*msg)


class Flow(BaseException):
    "Flow control indication."

    def __init__(self, n):
        self.n = n


@as_proxy("_CSMErr")
class StopMe(StreamError):
    "Unspecified Stop"

    pass


@as_proxy("_CSDErr")
class SkippedData(StreamError):
    "Data skipped, took too long"

    pass


@as_proxy("_CNsErr")
class NoStream(StreamError):
    "No streaming support"

    pass


@as_proxy("_CNCsErr")
class NoCmds(StreamError):
    "No support for any commands"

    pass


@as_proxy("_CNCErr")
class NoCmd(StreamError):
    "Unknown command"

    pass


@as_proxy("_CWSErr")
class WantsStream(StreamError):
    "API: NoStream called on a streaming endpoint"

    pass


@as_proxy("_CMSErr")
class MustStream(StreamError):
    "Requires streaming support"

    pass


__all__ = [
    "Flow",
    "LongCommandError",
    "MustStream",
    "NoCmd",
    "NoCmds",
    "NoStream",
    "NotReadyError",
    "RemoteError",
    "ShortCommandError",
    "SkippedData",
    "StopMe",
    "StreamError",
    "WantsStream",
]
