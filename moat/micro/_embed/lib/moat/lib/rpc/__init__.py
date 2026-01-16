"""
MoaT's command multiplexer.
"""
# ruff:noqa:I001

from __future__ import annotations

# Import constants directly (not lazy)
from .const import *  # noqa: F403

# Import errors directly
from .errors import *  # noqa: F403

# direct imports
from .base import BaseMsgHandler as BaseMsgHandler
from .base import Caller as Caller
from .base import MsgHandler as MsgHandler
from .base import MsgSender as MsgSender
from .base import SubMsgSender as SubMsgSender
from .cmd.base import APP as APP
from .cmd.base import BaseCmd as BaseCmd
from .cmd.base import LoadCmd as LoadCmd
from .cmd.base import LockBaseCmd as LockBaseCmd
from .cmd.base import RootCmd as RootCmd

from .cmd.array import ArrayCmd as ArrayCmd
from .cmd.tree.dir import BaseSuperCmd as BaseSuperCmd
from .cmd.tree.dir import DirCmd as DirCmd
from .cmd.tree.layer import BaseFwdCmd as BaseFwdCmd
from .cmd.tree.listen import BaseListenCmd as BaseListenCmd
from .cmd.tree.listen import BaseListenOneCmd as BaseListenOneCmd
from .msg import Msg as Msg
from .msg import MsgLink as MsgLink
from .msg import MsgResult as MsgResult
from .nest import CmdStream as CmdStream
from .nest import rpc_on_rpc as rpc_on_rpc
from .stream import HandlerStream as HandlerStream
from .stream import StreamLink as StreamLink
from .stream import i_f2wire as i_f2wire
from .stream import wire2i_f as wire2i_f
