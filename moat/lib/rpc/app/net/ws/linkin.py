"""
Websocket single-connection listener app.
"""

from __future__ import annotations

from moat.lib.rpc import BaseListenOneCmd
from moat.lib.rpc.conn.ws import WsIter
from moat.lib.stream import ws_stack


class LinkIn(BaseListenOneCmd):
    """
    An app that accepts a single websocket connection.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """

    def listener(self):
        """Returns the websocket listener."""
        return WsIter(
            self.cfg.get("host", "127.0.0.1"), self.cfg["port"], self.cfg.get("path", "/")
        )

    def wrapper(self, conn):
        """Wrap websocket blocks as an RPC message stream."""
        return ws_stack(conn, self.cfg)
