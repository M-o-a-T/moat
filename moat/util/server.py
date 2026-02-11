"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import anyio
from anyio.abc import SocketAttribute

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from ssl import SSLContext

    from anyio.abc import TaskGroup

__all__ = ["gen_ssl", "run_tcp_server"]


class _Server:
    """
    Wrapper for running a server.

    :meta public:
    """

    server: Any = None

    def __init__(
        self,
        tg: TaskGroup,
        handler: Callable[[Any], Awaitable[None]],
        _rdy: Callable[[Any], None] | None = None,
        port: int = 0,
        ssl: SSLContext | None = None,
        **kw: Any,
    ) -> None:
        self.tg: TaskGroup = tg
        self._kw: dict[str, Any] = kw
        self.ssl: SSLContext | None = ssl
        self._rdy: Callable[[Any], None] | None = _rdy
        self.handler: Callable[[Any], Awaitable[None]] = handler
        self.port: int = port

    async def _accept(self, conn: Any) -> None:
        conn_: Any = conn
        if self.ssl:
            conn_ = await anyio.streams.tls.TLSStream.wrap(  # type: ignore[attr-defined]  # anyio.streams.tls available at runtime
                conn,
                server_side=True,
                ssl_context=self.ssl,
            )
        await self.handler(conn_)

    async def run(self) -> None:
        """Run the server."""
        try:
            listener = await anyio.create_tcp_listener(local_port=self.port)
        except Exception as exc:
            raise OSError(f"could not listen to port {self.port}") from exc
        if not self.port:
            self.port = listener.extra_attributes[SocketAttribute.local_address]()[1]
        if self._rdy is not None:
            self._rdy(listener)
        async with listener:
            await listener.serve(self._accept)


async def run_tcp_server(*a: Any, **kv: Any) -> _Server:
    """
    A simple, possibly-SSL TCP server that runs a handler for each incoming connection
    """
    tg = kv.pop("tg", None)
    server: _Server
    if tg is not None:
        server = _Server(tg, *a, **kv)
        await server.run()
    else:
        async with anyio.create_task_group() as tg:
            server = _Server(tg, *a, **kv)
            await server.run()
    return server


def gen_ssl(
    ctx: bool | SSLContext | dict[str, str] = False,
    server: bool = True,
) -> SSLContext | None:
    """
    Generate a SSL config from the given context.

    Args:
      ctx: either a Bool (ssl yes/no) or a dict with "key" and "cert" entries.
      server: a flag whether to behave as a server.
    """
    if not ctx:
        return None
    if ctx is True:
        ctx = {}
    if not isinstance(ctx, dict):
        return ctx

    import ssl  # noqa: PLC0415

    ctx_ = ssl.create_default_context(
        purpose=ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH,
    )
    if "key" in ctx:
        ctx_.load_cert_chain(ctx["cert"], ctx["key"])
    return ctx_
