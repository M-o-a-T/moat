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
    from .asyncio import AIOBuf as AIOBuf
    from .asyncio import SingleAIOBuf as SingleAIOBuf
    from .cbor import CBORMsgBlk as CBORMsgBlk
    from .cbor import CBORMsgBuf as CBORMsgBuf
    from .log import LogBlk as LogBlk
    from .log import LogBuf as LogBuf
    from .log import LogMsg as LogMsg
    from .reliable import EphemeralMsg as EphemeralMsg
    from .reliable import ReliableMsg as ReliableMsg
    from .tcp import TcpLink as TcpLink


# Compatibility
class ProcessDeadError(Exception):
    "unused, compatibility"

    pass


# Lazy loading
_imports = {
    # Logging
    "LogMsg": "log",
    "LogBlk": "log",
    "LogBuf": "log",
    # CBOR
    "CBORMsgBuf": "cbor",
    "CBORMsgBlk": "cbor",
    # Asyncio
    "AIOBuf": "asyncio",
    "SingleAIOBuf": "asyncio",
    # Reliable messaging
    "ReliableMsg": "reliable",
    "EphemeralMsg": "reliable",
    # Network connections
    "TcpLink": "tcp",
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
    # Logging (lazy)
    "LogBlk",
    "LogBuf",
    "LogMsg",
    # CBOR (lazy)
    "CBORMsgBlk",
    "CBORMsgBuf",
    # Asyncio (lazy)
    "AIOBuf",
    "SingleAIOBuf",
    # Reliable messaging (lazy)
    "ReliableMsg",
    "EphemeralMsg",
    # Network connections (lazy)
    "TcpLink",
    # compatibility
    "ProcessDeadError",
]
