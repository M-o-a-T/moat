"""
This module contains various helper functions and classes.
"""
import anyio

__all__ = ["run_tcp_server"]


class _Server:
    server = None

    def __init__(self, tg, handler, _rdy=None, port=0, ssl=None, **kw):
        self.tg = tg
        self._kw = kw
        self.ssl = ssl
        self._rdy = _rdy
        self.handler = handler
        self.port = port

    async def _accept(self, conn):
        if self.ssl:
            conn = await anyio.streams.tls.TLSStream.wrap(
                conn, server_side=True, ssl_context=self.ssl
            )
        await self.handler(conn)

    async def run(self):
        listener = await anyio.create_tcp_listener(local_port=self.port)
        if self._rdy is not None:
            self._rdy(listener)
        async with listener:
            await listener.serve(self._accept)


async def run_tcp_server(*a, **kv) -> _Server:
    tg = kv.pop("tg", None)
    if tg is not None:
        server = _Server(tg, *a, **kv)
        await server.run()
    else:
        async with anyio.create_task_group() as tg:
            server = _Server(tg, *a, **kv)
            await server.run()
