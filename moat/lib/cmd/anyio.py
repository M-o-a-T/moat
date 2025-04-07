"""
Msghandler on top of anyio pipe
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
from moat.util.cbor import StdCBOR
from moat.util import ungroup
from typing import TYPE_CHECKING
from .stream import HandlerStream
import logging

if TYPE_CHECKING:
    from .base import BaseMsgHandler
    from moat.lib.codec import Codec

logger = logging.getLogger(__name__)


@asynccontextmanager
async def run(
    cmd: BaseMsgHandler, stream: anyio.abc.ByteStream, *, codec: Codec | None = None, debug: str = None
) -> MsgHandler:
    """
    Run a command handler on top of an anyio stream, using the given codec.

    @cmd is the handler for incoming messages. It may be `None`.

    This is an async context manager that yields the command handler.

    The default codec is `moat.util.cbor.Codec`.
    """

    if codec is None:
        from moat.util.cbor import StdCBOR

        codec = StdCBOR()

    elif isinstance(codec, str):
        from moat.lib.codec import get_codec

        codec = get_codec(codec)

    async def rd(conn, cmd, *, task_status):
        with anyio.CancelScope() as sc:
            task_status.started(sc)
            rd_ = conn.read if hasattr(conn, "read") else conn.receive
            while True:
                if debug:
                    logger.debug("R%s ?", debug)
                buf = await rd_(4096)
                if debug:
                    logger.debug("R%s %r", debug, buf)
                codec.feed(buf)
                for msg in codec:
                    if debug:
                        logger.debug("R%s %r", debug, msg)
                    await cmd.msg_in(msg)

    async def wr(conn, cmd):
        wr = conn.write if hasattr(conn, "write") else conn.send
        while True:
            try:
                msg = await cmd.msg_out()
            except EOFError:
                return
            if debug:
                logger.debug("W%s %r", debug, msg)

            buf = codec.encode(msg)
            if debug:
                logger.debug("W%s %r", debug, bytes(buf))
            await wr(buf)

    try:
        async with ungroup, stream, anyio.create_task_group() as tg:
            async with HandlerStream(cmd) as hs:
                rds = await tg.start(rd, stream, hs)
                tg.start_soon(wr, stream, hs)

                yield hs
            # Closing down, the HandlerStream's shutdown might require
            # exchanging more messages, after which it'll close its send queue.
            # Thus we don't cancel the writer.
            rds.cancel()
    except anyio.EndOfStream:
        pass
