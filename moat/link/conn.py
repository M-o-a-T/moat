"""
Connection and command helpers
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from moat.lib.cmd.anyio import run as run_stream
import anyio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import Msg


@asynccontextmanager
async def TCPConn(cmd: MsgSender | None, *a, codec: str = "std-cbor", debug=None, **kw):
    """
    Connection to a MoaT server.

    This encapsulates a TCP link to a remote side.

    Parameters:
    * the MsgHandler to connect to
    * all other arguments go to `anyio.connect_tcp`

    This is an async context manager, wrapping its `MsgHandler`
    argument.
    """
    async with (
        await anyio.connect_tcp(*a, **kw) as stream,
        run_stream(cmd, stream, codec=codec, debug=debug) as hdl,
    ):
        yield hdl
