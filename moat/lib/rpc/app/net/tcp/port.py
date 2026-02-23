"""
TCP multi-connection listener app.
"""

from __future__ import annotations

from moat.lib.rpc import BaseListenCmd
from moat.lib.rpc.conn.tcp import TcpIter


class Port(BaseListenCmd):
    """
    An app that accepts multiple TCP connections.
    """

    def listener(self):
        """Returns the TCP listener."""
        return TcpIter(self.cfg.get("host", "127.0.0.1"), self.cfg["port"])
