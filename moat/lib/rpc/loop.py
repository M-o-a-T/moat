"""
Loopback helpers for RPC streams.
"""

from __future__ import annotations

from moat.lib.micro import log, shield
from moat.util.exc import ungroup

from .const import B_FLAGSTR
from .stream.base import HandlerStream, wire2i_f

try:
    import anyio
except ImportError:
    import asyncio

    def cancelled_class():
        return asyncio.CancelledError

else:
    cancelled_class = anyio.get_cancelled_exc_class

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import MsgHandler

__all__ = ["StreamLoop"]


class StreamLoop(HandlerStream):
    "A test stream that implements loopback"

    __other: StreamLoop = None

    def __init__(self, h: MsgHandler, s: str):
        super().__init__(h)
        self.__s = s

    def attach_remote(self, other):
        "attach the other end to us"
        self.__other = other

    async def write_stream(self):
        "write loop"
        while True:
            try:
                msg = await self.msg_out()
            except EOFError:
                return
            m = msg[:]
            i, fl = wire2i_f(m.pop(0))
            f = B_FLAGSTR[fl]
            if i >= 0:
                f += "+"
            f += str(i)

            log("%s: %s %s", self.__s, f, " ".join(repr(x) for x in m))
            await self.__other.msg_in(msg)

    async def read_stream(self):
        "read loop. No-op; all work is done by the other side's writer."
        await self.__other.writer_done.wait()

    async def __aexit__(self, *tb):
        with shield():
            await self.__other.closed_input()
        try:
            with ungroup:
                await super().__aexit__(*tb)
        finally:
            if not self.is_idle:
                log("*** WARNING *** %r: not idle; %r", self, vars(self))
            # assert self.is_idle

        if isinstance(ungroup.one(tb[1]), cancelled_class()):
            return True
