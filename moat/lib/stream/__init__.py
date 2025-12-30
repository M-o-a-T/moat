"""
Stream infrastructure for handling data streams in a structured manner.
"""

from __future__ import annotations

# Import base classes directly (not lazy)
from .base import Base as Base
from .base import BaseBlk as BaseBlk
from .base import BaseBuf as BaseBuf
from .base import BaseConn as BaseConn
from .base import BaseMsg as BaseMsg
from .base import StackedBlk as StackedBlk
from .base import StackedBuf as StackedBuf
from .base import StackedConn as StackedConn
from .base import StackedMsg as StackedMsg

from typing import TYPE_CHECKING as _TC

if _TC:
    from .anyio import AnyioBuf as AnyioBuf
    from .anyio import BufAnyio as BufAnyio
    from .anyio import FilenoBuf as FilenoBuf
    from .anyio import ProcessBuf as ProcessBuf
    from .anyio import ProcessDeadError as ProcessDeadError
    from .anyio import RemoteBufAnyio as RemoteBufAnyio
    from .anyio import SingleAnyioBuf as SingleAnyioBuf
    from .cbor import CBORMsgBlk as CBORMsgBlk
    from .cbor import CBORMsgBuf as CBORMsgBuf
    from .log import LogBlk as LogBlk
    from .log import LogBuf as LogBuf
    from .log import LogMsg as LogMsg
    from .reliable import EphemeralMsg as EphemeralMsg
    from .reliable import ReliableMsg as ReliableMsg
    from .tcp import TcpLink as TcpLink
    from .terminal import FilenoTerm as FilenoTerm
    from .terminal import TermBuf as TermBuf
    from .unix import UnixLink as UnixLink


# Lazy loading
_imports = {
    # Logging
    "LogMsg": "log",
    "LogBlk": "log",
    "LogBuf": "log",
    # CBOR
    "CBORMsgBuf": "cbor",
    "CBORMsgBlk": "cbor",
    # AnyIO
    "ProcessDeadError": "anyio",
    "AnyioBuf": "anyio",
    "FilenoBuf": "anyio",
    "RemoteBufAnyio": "anyio",
    "BufAnyio": "anyio",
    "SingleAnyioBuf": "anyio",
    "ProcessBuf": "anyio",
    # Reliable messaging
    "ReliableMsg": "reliable",
    "EphemeralMsg": "reliable",
    # Network connections
    "TcpLink": "tcp",
    "UnixLink": "unix",
    # Terminal
    "FilenoTerm": "terminal",
    "TermBuf": "terminal",
}


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, True, 1), attr)
    globals()[attr] = value
    return value


__all__ = [
    # Base classes (not lazy)
    "Base",
    "BaseBlk",
    "BaseBuf",
    "BaseConn",
    "BaseMsg",
    "StackedBlk",
    "StackedBuf",
    "StackedConn",
    "StackedMsg",
] + list(_imports.keys())


def __dir__():
    return __all__
