"""
Apps for Unix socket connectivity
"""

from __future__ import annotations

from moat.micro.proto.unix import Link as UnixLink
from moat.micro.stacks.console import console_stack
from moat.util.compat import AC_use

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


def Raw(*a, **k):
    """Sends/receives raw data"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415

    class _Raw(BaseCmdBBM):
        def stream(self) -> Awaitable:
            return AC_use(self, UnixLink(self.port))

    return _Raw(*a, **k)


def Link(*a, **k):
    """
    An app that connects to a remote socket.
    """
    from moat.micro.cmd.stream.cmdmsg import CmdMsg  # noqa: PLC0415

    class _Link(CmdMsg):
        def __init__(self, cfg):
            stack = console_stack(UnixLink(cfg["port"]), cfg)
            super().__init__(stack, cfg)

    return _Link(*a, **k)


def LinkIn(*a, **k):
    """
    An app that accepts a single connection from a remote socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """
    from moat.micro.cmd.tree.listen import BaseListenOneCmd  # noqa: PLC0415
    from moat.micro.stacks.unix import UnixIter  # noqa: PLC0415

    class _LinkIn(BaseListenOneCmd):
        def listener(self):
            return UnixIter(self.cfg["port"])

    return _LinkIn(*a, **k)


def Port(*a, **k):
    """
    An app that accepts multiple Unix connections.
    """
    from moat.micro.cmd.tree.listen import BaseListenCmd  # noqa: PLC0415
    from moat.micro.stacks.unix import UnixIter  # noqa: PLC0415

    class _Port(BaseListenCmd):
        def listener(self):
            return UnixIter(self.cfg["port"])

    return _Port(*a, **k)
