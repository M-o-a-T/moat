"""
Connection and command helpers
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from moat.lib.cmd.anyio import run as run_stream
import anyio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AsyncContextManager
    from moat.lib.cmd import MsgSender
    from moat.lib.codec import Codec


@asynccontextmanager
async def TCPConn(cmd: MsgSender | None, *a, codec: str|Codec = "std-cbor", debug:bool=False, logger=None, **kw) -> AsyncGenerator[..., MsgSender]:
    """
    Connection to a MoaT server.

    This encapsulates a TCP link to a remote side.

    Parameters:
    * the MsgHandler to connect to
    * all other arguments go to `anyio.connect_tcp`

    This is an async context manager. It forwards incoming commands to @cmd
    and yields a `MsgSender` that forwards local to the remote side.
    """
    async with (
        await anyio.connect_tcp(*a, **kw) as stream,
        run_stream(cmd, stream, codec=codec, debug=debug, logger=logger) as hdl,
    ):
        yield hdl

@asynccontextmanager
async def UnixConn(cmd: MsgSender | None, *a, codec: str|Codec = "std-cbor", debug:bool=False, logger=None, **kw) -> AsyncGenerator[..., MsgSender]:
    """
    Connection to a MoaT server.

    This encapsulates a Unix-domain client link.

    Parameters:
    * the MsgHandler to connect to
    * all other arguments go to `anyio.connect_unix`

    This is an async context manager. It forwards incoming commands to @cmd
    and yields a `MsgSender` that forwards local to the remote side.
    """
    async with (
        await anyio.connect_unix(*a, **kw) as stream,
        run_stream(cmd, stream, codec=codec, debug=debug, logger=logger) as hdl,
    ):
        yield hdl
