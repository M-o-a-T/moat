"""
Connection handling for websocket listeners.
"""

from __future__ import annotations

from moat.lib.stream import SingleWsBlk

from .tcp import TcpIter


class WsIter(TcpIter):
    """
    A connection iterator for websocket connections.

    @host: address to listen on. No default.

    @port: port to listen on. Use 0 for an OS-assigned port;
        the actual port is available via
        :attr:`~moat.lib.rpc.conn.util.BaseConnIter.port` after startup.

    @path: websocket path. Defaults to ``/``.
    """

    def __init__(self, host, port, path="/"):
        super().__init__(host, port)
        self.path = path

    async def _handle(self, client):
        await self.add_conn(SingleWsBlk(client, path=self.path))
