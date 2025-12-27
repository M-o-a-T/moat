# ruff:noqa:F405
"""
MoaT's command multiplexer.
"""

from __future__ import annotations

# Import constants directly (not lazy)
from .const import *  # noqa: F403

# Import errors directly
from .errors import *  # noqa: F403

from typing import TYPE_CHECKING as _TC

if _TC:
    from .anyio import AioStream as AioStream
    from .base import BaseMsgHandler as BaseMsgHandler
    from .base import Caller as Caller
    from .base import Key as Key
    from .base import MsgHandler as MsgHandler
    from .base import MsgLink as MsgLink
    from .base import MsgSender as MsgSender
    from .base import OptDict as OptDict
    from .base import SubMsgSender as SubMsgSender
    from .msg import Msg as Msg
    from .msg import MsgResult as MsgResult
    from .nest import CmdStream as CmdStream
    from .nest import rpc_on_rpc as rpc_on_rpc
    from .stream import HandlerStream as HandlerStream
    from .stream import StreamLink as StreamLink
    from .stream import i_f2wire as i_f2wire
    from .stream import wire2i_f as wire2i_f


# Lazy loading for classes and functions
_lazy_imports = {
    # From anyio
    "rpc_on_aiostream": ".anyio",
    # From base
    "BaseMsgHandler": ".base",
    "Caller": ".base",
    "Key": ".base",
    "MsgHandler": ".base",
    "MsgLink": ".base",
    "MsgSender": ".base",
    "OptDict": ".base",
    "SubMsgSender": ".base",
    # From msg
    "Msg": ".msg",
    "MsgResult": ".msg",
    # From nest
    "rpc_on_rpc": ".nest",
    # From stream
    "HandlerStream": ".stream",
    "StreamLink": ".stream",
    "i_f2wire": ".stream",
    "wire2i_f": ".stream",
}


def __getattr__(name: str):
    if name in _lazy_imports:
        from importlib import import_module  # noqa:PLC0415

        mod = import_module(_lazy_imports[name], __name__)
        attr = getattr(mod, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [  # noqa:RUF022
    # From const (not lazy)
    "B_STREAM",
    "B_ERROR",
    "B_WARNING",
    "B_WARNING_INTERNAL",
    "B_FLAGSTR",
    "E_UNSPEC",
    "E_NO_STREAM",
    "E_CANCEL",
    "E_NO_CMDS",
    "E_SKIP",
    "E_MUST_STREAM",
    "E_ERROR",
    "E_NO_CMD",
    "S_END",
    "S_NEW",
    "S_ON",
    "S_OFF",
    "SD_NONE",
    "SD_IN",
    "SD_OUT",
    "SD_BOTH",
    # From errors (not lazy)
    "NotReadyError",
    "ShortCommandError",
    "LongCommandError",
    "RemoteError",
    "StreamError",
    "Flow",
    "StopMe",
    "SkippedData",
    "NoStream",
    "NoCmds",
    "NoCmd",
    "WantsStream",
    "MustStream",
    # From anyio (lazy via TYPE_CHECKING)
    "AioStream",
    "rpc_on_aiostream",
    # From base (lazy via TYPE_CHECKING)
    "BaseMsgHandler",
    "Caller",
    "Key",
    "MsgHandler",
    "MsgLink",
    "MsgSender",
    "OptDict",
    "SubMsgSender",
    # From msg (lazy via TYPE_CHECKING)
    "Msg",
    "MsgResult",
    # From nest (lazy via TYPE_CHECKING)
    "CmdStream",
    "rpc_on_rpc",
    # From stream (lazy via TYPE_CHECKING)
    "HandlerStream",
    "StreamLink",
    "i_f2wire",
    "wire2i_f",
]
