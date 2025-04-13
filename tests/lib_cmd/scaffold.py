from __future__ import annotations
import anyio
from moat.lib.cmd.base import MsgSender, MsgHandler, MsgLink
from moat.lib.cmd.msg import Msg
from moat.lib.cmd.stream import HandlerStream
from moat.util import Path, CtxObj, ungroup
from moat.util.compat import shield
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)


def res_akw(a, kw):
    sa = "-" if not a else "|".join((str(x) if isinstance(x, Path) else repr(x)) for x in a)
    sk = "-" if not kw else "|".join(f"{k}={v!r}" for k, v in kw.items())
    return sa + " " + sk


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.msg import Msg


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
            logger.debug("%s: %r", self.__s, msg)
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
            assert self.is_idle

        if isinstance(ungroup.one(tb[1]),anyio.get_cancelled_exc_class()):
            return True


async def _wrap_sock(s: Socket) -> anyio.abc.ByteStream:
    import sniffio

    if sniffio.current_async_library() == "asyncio":
        import asyncio

        return anyio._backends._asyncio.SocketStream(
            *(
                await asyncio.get_running_loop().create_connection(
                    anyio._backends._asyncio.StreamProtocol,
                    sock=s,
                )
            )
        )
    elif sniffio.current_async_library() == "trio":
        import trio

        return anyio._backends._trio.SocketStream(trio.socket.from_stdlib_socket(s))
    else:
        raise RuntimeError("Which anyio backend are you using??")


class StreamGate(CtxObj):
    def __init__(self, h: MsgHandler, so: Socket, s: str):
        from moat.util.cbor import StdCBOR

        self.s = s
        self.so = so
        self.h = h

    @asynccontextmanager
    async def _ctx(self):
        from moat.lib.cmd.anyio import run
        from contextlib import nullcontext

        async with await _wrap_sock(self.so) as sock, run(self.h, sock, debug=self.s) as out:
            yield out
            # await anyio.sleep(0.1)
            if not out.root.is_idle:
                logger.warning("NOT IDLE: Error?")
                while not out.root.is_idle:
                    await anyio.sleep(0.1)
                logger.warning("NOT IDLE: OK")
            assert out.root.is_idle


@asynccontextmanager
async def scaffold(ha, hb, key="", use_socket=False):
    if use_socket:
        import socket

        sa, sb = socket.socketpair()
        a = StreamGate(ha, sa, key + ">")
        b = StreamGate(hb, sb, key + "<")
    else:
        a = StreamLoop(ha, key + ">")
        b = StreamLoop(hb, key + "<")
        a.attach_remote(b)
        b.attach_remote(a)
    async with a as xa, b as xb:
        yield MsgSender(xa), MsgSender(xb)
    # assert not a._msgs, a._msgs
    # assert not b._msgs, b._msgs
