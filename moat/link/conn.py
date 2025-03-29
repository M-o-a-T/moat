"""
Connection and command helpers
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from moat.lib.cmd.anyio import run as run_stream
import anyio
import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import CmdHandler
    from collections.abc import Awaitable

__all__ = ["NotAuthorized", "SubConn", "CmdCommon", "TCPConn"]

logger = logging.getLogger(__name__)


class NotAuthorized(RuntimeError):
    pass


class SubConn:
    _handler: CmdHandler

    def cmd(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._handler.cmd(*a, **kw)

    def stream_r(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._handler.stream_r(*a, **kw)

    def stream_w(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._handler.stream_w(*a, **kw)

    def stream_rw(self, *a, **kw) -> Awaitable:
        "Forwarded to the link"
        return self._handler.stream_rw(*a, **kw)


class CmdCommon:
    async def cmd_i_ping(self, msg) -> bool | None:
        """
        乒 ⇒ 乓

        Yes, this is silly, but we gotta test basic UTF-8 compliance *somehow*.
        """
        await msg.result("乓", *msg.args, **msg.kw)

    cmd_i_乒 = cmd_i_ping


@asynccontextmanager
async def TCPConn(cmd: CmdHandler, *a, **kw):
    """
    Connection to a MoaT server.

    This encapsulates a TCP link to a remote side.

    Parameters:
    * the CmdHandler to connect to
    * all other arguments go to `anyio.connect_tcp`
    """
    async with (
        await anyio.connect_tcp(*a, **kw) as stream,
        run_stream(cmd, stream),
    ):
        yield cmd
