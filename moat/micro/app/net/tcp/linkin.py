"""
TCP single-connection listener app.
"""

from __future__ import annotations

from moat.lib.rpc import BaseListenOneCmd
from moat.lib.rpc.conn.tcp import TcpIter


class LinkIn(BaseListenOneCmd):
    """
    An app that accepts a single connection from a remote socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """

    def listener(self):
        """Returns the TCP listener."""
        return TcpIter(self.cfg.get("host", "127.0.0.1"), self.cfg["port"])
