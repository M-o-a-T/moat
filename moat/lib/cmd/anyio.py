"""
Msghandler on top of anyio pipe
"""

from __future__ import annotations

import anyio
import logging
from contextlib import asynccontextmanager

from moat.util import ungroup

from .stream import HandlerStream

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd import MsgHandler, MsgSender
    from moat.lib.codec import Codec

    from .base import BaseMsgHandler

logger = logging.getLogger(__name__)


class AioStream(HandlerStream):  # noqa: D101
    __codec: Codec

    def __init__(
        self,
        cmd: MsgSender,
        stream,
        debug: str | None = None,
        codec: str | Codec | None = None,
        **kw,
    ):
        self.__s = stream
        self.__debug = debug

        if codec is None:
            from moat.util.cbor import StdCBOR  # noqa: PLC0415

            codec = StdCBOR()

        elif isinstance(codec, str):
            from moat.lib.codec import get_codec  # noqa: PLC0415

            codec = get_codec(codec)

        self.__codec = codec
        super().__init__(cmd, **kw)

    async def read_stream(self):  # noqa: D102
        conn = self.__s
        codec = self.__codec
        rd_ = conn.read if hasattr(conn, "read") else conn.receive

        while True:
            if self.__debug:
                logger.debug("R%s ?", self.__debug)
            buf = await rd_(4096)
            if self.__debug:
                logger.debug("R%s %r", self.__debug, buf)
            codec.feed(buf)
            for msg in codec:
                if self.__debug:
                    logger.debug("R%s %r", self.__debug, msg)
                await self.msg_in(msg)

    async def write_stream(self):  # noqa: D102
        conn = self.__s
        codec = self.__codec
        wr = conn.write if hasattr(conn, "write") else conn.send
        while True:
            try:
                msg = await self.msg_out()
            except EOFError:
                return
            if self.__debug:
                logger.debug("W%s %r", self.__debug, msg)

            buf = codec.encode(msg)
            if self.__debug:
                logger.debug("W%s %r", self.__debug, bytes(buf))
            await wr(buf)


@asynccontextmanager
async def run(
    cmd: BaseMsgHandler,
    stream: anyio.abc.ByteStream,
    *,
    codec: Codec | str | None = None,
    debug: bool = False,
    logger=None,
) -> MsgHandler:
    """
    Run a command handler on top of an anyio stream, using the given codec.

    @cmd is the handler for incoming messages. It may be `None`.

    This is an async context manager that yields the command handler.

    The default codec is `moat.util.cbor.Codec`.
    """

    y = False
    try:
        async with (
            ungroup,
            stream,
            AioStream(cmd, stream, codec=codec, debug=debug, logger=logger) as hs,
        ):
            y = True
            yield hs
    except (anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError):
        if not y:
            raise
