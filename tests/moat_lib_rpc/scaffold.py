from __future__ import annotations  # noqa: D100

import anyio
import logging
from contextlib import asynccontextmanager

from moat.util import CtxObj, Path
from moat.lib.rpc._test import StreamLoop
from moat.lib.rpc.base import MsgHandler, MsgSender

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from socket import socket

logger = logging.getLogger(__name__)


def res_akw(a, kw):  # noqa: D103
    sa = "-" if not a else "|".join((str(x) if isinstance(x, Path) else repr(x)) for x in a)
    sk = "-" if not kw else "|".join(f"{k}={v!r}" for k, v in kw.items())
    return sa + " " + sk


async def _wrap_sock(s: socket) -> anyio.abc.ByteStream:
    import sniffio  # noqa: PLC0415

    if sniffio.current_async_library() == "asyncio":
        import asyncio  # noqa: PLC0415

        return anyio._backends._asyncio.SocketStream(  # noqa: SLF001
            *(
                await asyncio.get_running_loop().create_connection(
                    anyio._backends._asyncio.StreamProtocol,  # noqa: SLF001
                    sock=s,
                )
            )
        )
    elif sniffio.current_async_library() == "trio":
        import trio  # noqa: PLC0415

        return anyio._backends._trio.SocketStream(trio.socket.from_stdlib_socket(s))  # noqa: SLF001
    else:
        raise RuntimeError("Which anyio backend are you using??")


class StreamGate(CtxObj):  # noqa: D101
    def __init__(self, h: MsgHandler, so: socket, s: str):
        self.s = s
        self.so = so
        self.h = h

    @asynccontextmanager
    async def _ctx(self):
        from moat.lib.rpc.anyio import run  # noqa: PLC0415

        async with await _wrap_sock(self.so) as sock, run(self.h, sock, debug=self.s) as out:
            yield out
            # await anyio.sleep(0.1)
            if not out.root.is_idle:
                logger.warning("NOT IDLE: Error?")
                while not out.root.is_idle:  # noqa:ASYNC110
                    # TODO fix this?
                    await anyio.sleep(0.1)
                logger.warning("NOT IDLE: OK")
            assert out.root.is_idle


@asynccontextmanager
async def scaffold(ha, hb, key="", use_socket=False):  # noqa: D103
    if use_socket:
        import socket  # noqa: PLC0415

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
