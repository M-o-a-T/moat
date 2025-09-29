"""
Test support
"""

from __future__ import annotations

from moat.lib.cmd.const import B_FLAGSTR
from moat.lib.cmd.stream import wire2i_f
from moat.util.compat import log, shield
from moat.util.exc import ungroup

try:
    import anyio
except ImportError:
    import asyncio

    def cancelled_class():
        return asyncio.CancelledError

else:
    cancelled_class = anyio.get_cancelled_exc_class

from .stream import HandlerStream

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import MsgHandler


class StreamLoop(HandlerStream):
    __other: StreamLoop = None

    def __init__(self, h: MsgHandler, s: str):
        super().__init__(h)
        self.__s = s

    def attach_remote(self, other):
        self.__other = other

    async def write_stream(self):
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
