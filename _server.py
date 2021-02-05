"""
This module contains various helper functions and classes.
"""
import trio
import anyio

from typing import Union, Dict, Optional
from ssl import SSLContext
from sniffio import current_async_library
from contextlib import asynccontextmanager

__all__ = ["create_tcp_server", "gen_ssl"]


class _Server:
    _servers = None
    recv_q = None

    def __init__(self, tg, port=0, ssl=None, **kw):
        self.tg = tg
        self.port = port
        self.ports = None
        self._kw = kw
        self.ssl = ssl

    async def _accept(self, server, q):
        self.ports.append(server.socket.getsockname())
        try:
            while True:
                conn = await server.accept()
                if self.ssl:
                    conn = trio.SSLStream(conn, self.ssl, server_side=True)
                await q.send(conn)
        finally:
            async with anyio.fail_after(2, shield=True):
                await q.aclose()
                await server.aclose()

    async def __aenter__(self):
        if current_async_library() != "trio":
            raise RuntimeError("This only works with Trio right now.Sorry.")
        send_q, self.recv_q = trio.open_memory_channel(1)
        try:
            servers = await trio.open_tcp_listeners(self.port, **self._kw)
        except EnvironmentError as exc:
            err = OSError(f"Port {self.port} in use")
            err.errno = exc.errno
            raise err from exc

        self.ports = []
        async with send_q:
            for s in servers:
                await self.tg.spawn(self._accept, s, send_q.clone())
        return self

    async def __aexit__(self, *tb):
        await self.tg.cancel_scope.cancel()
        async with anyio.fail_after(2, shield=True):
            await self.recv_q.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv_q.receive()
        except trio.EndOfChannel:
            raise StopAsyncIteration


@asynccontextmanager
async def create_tcp_server(**args) -> _Server:
    async with anyio.create_task_group() as tg:
        server = _Server(tg, **args)
        async with server:
            yield server


def gen_ssl(
    ctx: Union[bool, SSLContext, Dict[str, str]] = False, server: bool = True
) -> Optional[SSLContext]:
    """
    Generate a SSL config from the given context.

    Args:
      ctx: either a Bool (ssl yes/no) or a dict with "key" and "cert" entries.
      server: a flag whether to behave as a server.
    """
    if not ctx:
        return None
    if ctx is True:
        ctx = dict()
    if not isinstance(ctx, dict):
        return ctx

    # pylint: disable=no-member
    ctx_ = trio.ssl.create_default_context(
        purpose=trio.ssl.Purpose.CLIENT_AUTH if server else trio.ssl.Purpose.SERVER_AUTH
    )
    if "key" in ctx:
        ctx_.load_cert_chain(ctx["cert"], ctx["key"])
    return ctx_
