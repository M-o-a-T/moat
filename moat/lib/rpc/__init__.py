# ruff:noqa:F405
"""
MoaT's command multiplexer.
"""

from __future__ import annotations

from moat import DOC as _DOC

# Import BaseMsgHandler at runtime for Sphinx documentation
from .base import BaseMsgHandler as BaseMsgHandler

# Import constants directly (not lazy)
from .const import *  # noqa: F403

# Import errors directly
from .errors import *  # noqa: F403

from typing import TYPE_CHECKING as _TC

# Lazy loading for classes and functions
_imports = {
    # From anyio
    "rpc_on_aiostream": "anyio",
    # From base
    "BaseMsgHandler": "base",
    "Caller": "base",
    "Key": "base",
    "MsgHandler": "base",
    "MsgSender": "base",
    "OptDict": "base",
    "SubMsgSender": "base",
    # From cmd.array
    "ArrayCmd": "cmd.array",
    # From cmd._base and cmd.base
    "BaseCmd": "cmd._base",
    "LoadCmd": "cmd._base",
    "LockBaseCmd": "cmd._base",
    "RootCmd": "cmd.base",
    # From cmd.tree.dir
    "BaseSubCmd": "cmd.tree.dir",
    "BaseSuperCmd": "cmd.tree.dir",
    "CfgStore": "cmd.tree.dir",
    "DirCmd": "cmd.tree.dir",
    "SubStore": "cmd.tree.dir",
    # From cmd.tree.layer
    "BaseFwdCmd": "cmd.tree.layer",
    "BaseLayerCmd": "cmd.tree.layer",
    # From cmd.tree.listen
    "BaseListenCmd": "cmd.tree.listen",
    "BaseListenOneCmd": "cmd.tree.listen",
    # From msg
    "Msg": "msg",
    "MsgLink": "msg",
    "MsgResult": "msg",
    # From nest
    "rpc_on_rpc": "nest",
    # From stream
    "HandlerStream": "stream",
    "StreamLink": "stream",
    "i_f2wire": "stream",
    "wire2i_f": "stream",
    # From log
    "Logger": "cmd.log",
}


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), attr)
    globals()[attr] = value
    return value


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
    # From errors
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
    # From anyio
    "AioStream",
    "rpc_on_aiostream",
    # From base
    "BaseMsgHandler",
    "Caller",
    "Key",
    "MsgHandler",
    "MsgSender",
    "OptDict",
    "SubMsgSender",
    # From cmd.array
    "ArrayCmd",
    # From cmd.base
    "BaseCmd",
    "LoadCmd",
    "LockBaseCmd",
    "RootCmd",
    # From cmd.tree.dir
    "BaseSubCmd",
    "BaseSuperCmd",
    "CfgStore",
    "DirCmd",
    "SubStore",
    # From cmd.tree.layer
    "BaseFwdCmd",
    "BaseLayerCmd",
    # From cmd.tree.listen
    "BaseListenCmd",
    "BaseListenOneCmd",
    # From msg
    "Msg",
    "MsgLink",
    "MsgResult",
    # From nest
    "CmdStream",
    "rpc_on_rpc",
    # From stream
    "HandlerStream",
    "StreamLink",
    "i_f2wire",
    "wire2i_f",
    # From log
    "Logger",
]

if _TC or _DOC:
    _DOC = False
    from .anyio import AioStream as AioStream
    from .base import Caller as Caller
    from .base import Key as Key
    from .base import MsgHandler as MsgHandler
    from .base import MsgSender as MsgSender
    from .base import OptDict as OptDict
    from .base import SubMsgSender as SubMsgSender
    from .cmd._base import BaseCmd as BaseCmd
    from .cmd._base import LoadCmd as LoadCmd
    from .cmd._base import LockBaseCmd as LockBaseCmd
    from .cmd.array import ArrayCmd as ArrayCmd
    from .cmd.base import RootCmd as RootCmd
    from .cmd.log import Logger as Logger
    from .cmd.tree.dir import BaseSubCmd, BaseSuperCmd, CfgStore, SubStore
    from .cmd.tree.layer import BaseFwdCmd, BaseLayerCmd
    from .cmd.tree.listen import BaseListenCmd, BaseListenOneCmd
    from .msg import Msg as Msg
    from .msg import MsgLink as MsgLink
    from .msg import MsgResult as MsgResult
    from .nest import CmdStream as CmdStream
    from .nest import rpc_on_rpc as rpc_on_rpc
    from .stream import HandlerStream as HandlerStream
    from .stream import StreamLink as StreamLink
    from .stream import i_f2wire as i_f2wire
    from .stream import wire2i_f as wire2i_f
