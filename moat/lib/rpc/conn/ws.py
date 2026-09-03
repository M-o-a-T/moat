"""
Connection handling for websocket listeners.
"""

from __future__ import annotations

from moat.lib.stream import SingleWsBlk

from .tcp import TcpIter


class WsIter(TcpIter):
    """
    A connection iterator for websocket connections.


    @path: websocket path. Defaults to ``/``.
    Args:
        host: Address to listen on. No default.
        port: Port to listen on. Use 0 for an OS-assigned port;
            the actual port is available via
            :attr:`~moat.lib.rpc.conn.util.BaseConnIter.port` after startup.
        path: Websocket path. Defaults to ``/``.
        subprotocols: Optional list of WebSocket subprotocols to negotiate
            during the handshake. Passed through to :class:`~moat.lib.stream.SingleWsBlk`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        path: str = "/",
        *,
        subprotocols: list[str] | None = None,
    ):
        super().__init__(host, port)
        self.path = path
        self.subprotocols = subprotocols

    async def _handle(self, client):
        await self.add_conn(SingleWsBlk(client, path=self.path, subprotocols=self.subprotocols))
