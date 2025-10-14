"""
# MsgHandler on top of a message stream

MoaT-Cmd offers no way to discover who your caller is. This is sometimes
inconvenient.

As a real-world example, assume you have an embedded device that's
connected to some environmental sensors and a ventilator, so it needs to
calculate the air quality. Assume further that the library to do this
is too large, or closed-source with binaries not available for its
architecture (hello, Bosch, please reconsider), or single-theaded but the
embedded device doesn't have threads.

So you use MoaT-Cmd to call out to your server, which has the library. The
library then wants to access your embedded device's i²c bus to actually
read the data, but it doesn't have its address.

The solution is to multiplex the stream to the server … with error handling,
streaming the resulting measurements, and all that. But why re-invent the
wheel, when MoaT-Cmd already *is* a multiplexing library, and you're using
it anyway?

Hence this stream handler.

See ``tests/moat_lib_cmd/test_nest.py`` for an example.

"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from moat.util import ungroup

from .stream import HandlerStream

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.base import MsgHandler, MsgSender
    from moat.lib.cmd.msg import Msg

    from .base import BaseMsgHandler

logger = logging.getLogger(__name__)


class CmdStream(HandlerStream):
    """
    This command stream uses the data from a single message as its
    transport.

    Args:
        cmd: the command handler to call for incoming commands.
             May be ``None`` if you don't handle any.
        msg: the stream to use. **It must be wrapped in an `async with
             msg.stream()` block.**
        debug: Prefix for tracing. Note that the trace handles raw
               message data and does not decode transactions.
    """

    __msg: Msg

    def __init__(
        self,
        cmd: MsgSender | None,
        msg: Msg,
        debug: str | None = None,
        **kw,
    ):
        self.__msg = msg
        self.__debug = debug

        super().__init__(cmd, **kw)

    async def read_stream(self):  # noqa: D102
        msg = self.__msg

        async for m in msg:
            if m.kw:
                logger.debug("R%s: incoming keywords ignored!? %r", self.__debug or "", m)
            elif self.__debug:
                logger.debug("R%s %r", self.__debug, m)
            await self.msg_in(m.args_l)

    async def write_stream(self):  # noqa: D102
        msg = self.__msg
        while True:
            try:
                m = await self.msg_out()
            except EOFError:
                return
            if self.__debug:
                logger.debug("W%s %r", self.__debug, m)

            await msg.send(*m)


@asynccontextmanager
async def run(
    cmd: BaseMsgHandler,
    msg: Msg,
    *,
    debug: bool = False,
    logger=None,
) -> MsgHandler:
    """
    Run a command handler on top of a message stream @msg.

    @cmd is the handler for incoming messages. It may be `None`.

    This is an async context manager that yields a `CmdStream`.
    """

    async with ungroup, CmdStream(cmd, msg, debug=debug, logger=logger) as hs:
        yield hs
