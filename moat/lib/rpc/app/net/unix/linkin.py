"""
Unix socket single-connection listener app.
"""

from __future__ import annotations

from moat.lib.rpc import BaseListenOneCmd
from moat.lib.rpc.conn.unix import UnixIter


class LinkIn(BaseListenOneCmd):
    """
    An app that accepts a single connection from a remote Unix socket.

    New connections may or may not supersede existing ones, depending on the
    "replace" config item.
    """

    def listener(self):
        """Returns the Unix socket listener."""
        return UnixIter(self.cfg["port"])
