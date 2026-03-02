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
    # From cmd.retry
    "RetryCmd": "cmd.retry",
    # From cmd._base and cmd.base
    "APP": "cmd._base",  # not exported/documented
    "add_app_prefix": "cmd._base",
    "load_app": "cmd._base",
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
    # From conn
    "BaseConnIter": "conn.util",
    "TcpIter": "conn.tcp",
    "UnixIter": "conn.unix",
    "WsIter": "conn.ws",
    # From msg
    "Msg": "msg",
    "MsgLink": "msg",
    "MsgResult": "msg",
    # From nest
    "rpc_on_rpc": "nest",
    # From stream.base
    "HandlerStream": "stream.base",
    "StreamLink": "stream.base",
    "i_f2wire": "stream.base",
    "wire2i_f": "stream.base",
    # From stream.cmdbbm
    "BaseCmdBBM": "stream.cmdbbm",
    # From cmd.msg
    "MsgStream": "cmd.msg",
    "BaseCmdMsg": "cmd.msg",
    "CmdMsg": "cmd.msg",
    "SingleCmdMsg": "cmd.msg",
    "ExtCmdMsg": "cmd.msg",
    # From stream.xcmd
    "BBMCmd": "stream.xcmd",
    "MsgCmd": "stream.xcmd",
    "BufCmd": "stream.xcmd",
    "BlkCmd": "stream.xcmd",
    # From log
    "Logger": "cmd.log",
    # From auth
    "Auth": "auth._base",
    # From alert
    "Alert": "alert",
    "AlertHandler": "alert",
}


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, (attr,), 1), attr)
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
    # From cmd.retry
    "RetryCmd",
    # From cmd.base
    "BaseCmd",
    "add_app_prefix",
    "load_app",
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
    # From conn
    "BaseConnIter",
    "TcpIter",
    "UnixIter",
    "WsIter",
    # From msg
    "Msg",
    "MsgLink",
    "MsgResult",
    # From nest
    "CmdStream",
    "rpc_on_rpc",
    # From stream.base
    "HandlerStream",
    "StreamLink",
    "i_f2wire",
    "wire2i_f",
    # From stream.cmdbbm
    "BaseCmdBBM",
    # From cmd.msg
    "MsgStream",
    "BaseCmdMsg",
    "CmdMsg",
    "SingleCmdMsg",
    "ExtCmdMsg",
    # From stream.xcmd
    "BBMCmd",
    "MsgCmd",
    "BufCmd",
    "BlkCmd",
    # From log
    "Logger",
    # From auth
    "Auth",
    # From alert
    "Alert",
    "AlertHandler",
]

if _TC or _DOC:
    _DOC = False
    from .anyio import AioStream as AioStream  # noqa:I001
    from .base import Caller as Caller
    from .base import Key as Key
    from .base import MsgHandler as MsgHandler
    from .base import MsgSender as MsgSender
    from .base import OptDict as OptDict
    from .base import SubMsgSender as SubMsgSender
    from .cmd._base import BaseCmd as BaseCmd
    from .cmd._base import add_app_prefix as add_app_prefix
    from .cmd._base import load_app as load_app
    from .cmd._base import LoadCmd as LoadCmd
    from .cmd._base import LockBaseCmd as LockBaseCmd
    from .cmd.array import ArrayCmd as ArrayCmd
    from .cmd.retry import RetryCmd as RetryCmd
    from .cmd.base import RootCmd as RootCmd
    from .cmd.log import Logger as Logger
    from .cmd.tree.dir import BaseSubCmd, BaseSuperCmd, CfgStore, SubStore
    from .cmd.tree.layer import BaseFwdCmd, BaseLayerCmd
    from .cmd.tree.listen import BaseListenCmd, BaseListenOneCmd
    from .conn.tcp import TcpIter as TcpIter
    from .conn.unix import UnixIter as UnixIter
    from .conn.util import BaseConnIter as BaseConnIter
    from .conn.ws import WsIter as WsIter
    from .msg import Msg as Msg
    from .msg import MsgLink as MsgLink
    from .msg import MsgResult as MsgResult
    from .stream.base import HandlerStream as HandlerStream
    from .stream.base import StreamLink as StreamLink
    from .stream.base import i_f2wire as i_f2wire
    from .stream.base import wire2i_f as wire2i_f
    from .stream.cmdbbm import BaseCmdBBM as BaseCmdBBM
    from .cmd.msg import BaseCmdMsg as BaseCmdMsg
    from .cmd.msg import CmdMsg as CmdMsg
    from .cmd.msg import ExtCmdMsg as ExtCmdMsg
    from .cmd.msg import MsgStream as MsgStream
    from .cmd.msg import SingleCmdMsg as SingleCmdMsg
    from .stream.xcmd import BBMCmd as BBMCmd
    from .stream.xcmd import BlkCmd as BlkCmd
    from .stream.xcmd import BufCmd as BufCmd
    from .stream.xcmd import MsgCmd as MsgCmd
    from .nest import CmdStream as CmdStream
    from .nest import rpc_on_rpc as rpc_on_rpc
    from .alert import Alert as Alert
    from .alert import AlertHandler as AlertHandler
    from .auth._base import Auth as Auth
