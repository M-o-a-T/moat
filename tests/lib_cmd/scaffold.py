from __future__ import annotations
import anyio
from moat.lib.cmd.base import MsgSender, MsgHandler, MsgLink
from moat.lib.cmd.msg import Msg
from moat.lib.cmd.stream import HandlerStream
from moat.util import Path
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


class LogLink(MsgLink):
    def __init__(self, rem: MsgLink, s: str):
        self._s = s
        self._rem = rem

    def ml_recv(self, a: list, kw: dict, flags: int) -> None:
        logger.debug("T:%s %s %d", self._s, res_akw(a, kw), flags)
        self._remote.ml_recv(a, kw, flags)


class StreamLoop(HandlerStream):
    __other: StreamLoop = None

    def __init__(self, h: MsgHandler, s: str):
        super().__init__(h)
        self.__s = s

    def attach_remote(self, other):
        self.__other = other

    async def __send(self):
        while True:
            msg = await self.msg_out()
            logger.warning("%s: %r", self.__s, msg)
            self.__other.msg_in(msg)

    @asynccontextmanager
    async def _ctx(self):
        async with super()._ctx():
            self.start(self.__send)
            yield self
            if not self.is_idle:
                logger.debug("NOT IDLE")
                while not self.is_idle:
                    await anyio.sleep(0.1)
                logger.debug("NOW IDLE")
            assert self.is_idle


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


class StreamGate(HandlerStream):
    def __init__(self, h: MsgHandler, so: Socket, s: str):
        from moat.util.cbor import StdCBOR

        super().__init__(h)
        self.__s = s
        self.__so = so

    @asynccontextmanager
    async def _ctx(self):
        from moat.lib.cmd.anyio import run
        from contextlib import nullcontext

        async with await _wrap_sock(self.__so) as sock, run(super()._ctx(), sock, debug=self.__s):
            yield self
            # await anyio.sleep(0.1)
            if not self.is_idle:
                logger.warning("NOT IDLE: Error?")
                while not self.is_idle:
                    await anyio.sleep(0.1)
                logger.warning("NOT IDLE: OK")
            assert self.is_idle


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
    async with a, b:
        yield MsgSender(a), MsgSender(b)
    # assert not a._msgs, a._msgs
    # assert not b._msgs, b._msgs
