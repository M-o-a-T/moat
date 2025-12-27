"""
MoaT's command multiplexer.
"""

from __future__ import annotations

from .base import BaseMsgHandler as BaseMsgHandler
from .base import Caller as Caller
from .base import MsgHandler as MsgHandler
from .base import MsgLink as MsgLink
from .base import MsgSender as MsgSender
from .base import SubMsgSender as SubMsgSender

# Import constants directly (not lazy)
from .const import *  # noqa: F403

# Import errors directly
from .errors import *  # noqa: F403
from .msg import Msg as Msg
from .msg import MsgResult as MsgResult
from .nest import CmdStream as CmdStream
from .nest import rpc_on_rpc as rpc_on_rpc
from .stream import HandlerStream as HandlerStream
from .stream import StreamLink as StreamLink
from .stream import i_f2wire as i_f2wire
from .stream import wire2i_f as wire2i_f
