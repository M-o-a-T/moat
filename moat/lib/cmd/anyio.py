"""
Msghandler on top of anyio pipe
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
from moat.util.cbor import StdCBOR
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .base import MsgHandler
    from moat.lib.codec import Codec

logger = logging.getLogger(__name__)


@asynccontextmanager
async def run(
    cmd: MsgHandler, stream: anyio.abc.ByteStream, *, codec: Codec | None = None, debug: str = None
):
    """
    Run a command handler on top of an anyio stream, using the given codec.

    @cmd is supposed to be an async context manager. Use `contextlib.nullcontext`
    if you need to call this from inside its context.

    This is an async context manager that yields the command handler.

    The default codec is `moat.util.cbor.Codec`.
    """

    if codec is None:
        from moat.util.cbor import StdCBOR

        codec = StdCBOR()

    async def rd(conn, cmd, *, task_status):
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            rd_ = conn.read if hasattr(conn, "read") else conn.receive
            while True:
                try:
                    if debug:
                        logger.warning("R%s ?", debug)
                    buf = await rd_(4096)
                except anyio.EndOfStream:
                    return
                if debug:
                    logger.warning("R%s %r", debug, buf)
                codec.feed(buf)
                for msg in codec:
                    if debug:
                        logger.warning("R%s %r", debug, msg)
                    cmd.msg_in(msg)

    async def wr(conn, cmd):
        wr = conn.write if hasattr(conn, "write") else conn.send
        while True:
            try:
                msg = await cmd.msg_out()
            except EOFError:
                return
            if debug:
                logger.warning("W%s %r", debug, msg)

            buf = codec.encode(msg)
            if debug:
                logger.warning("W%s %r", debug, bytes(buf))
            await wr(buf)

    async with anyio.create_task_group() as tg:
        async with cmd as cmd_:
            rds = await tg.start(rd, stream, cmd_)
            tg.start_soon(wr, stream, cmd_)
            yield cmd_
        rds.cancel()
        # we wait on the writer
