"""
Unix socket multi-connection listener app.
"""

from __future__ import annotations

from moat.lib.rpc import BaseListenCmd
from moat.micro.stacks.unix import UnixIter


class Port(BaseListenCmd):
    """
    An app that accepts multiple Unix socket connections.
    """

    def listener(self):
        """Returns the Unix socket listener."""
        return UnixIter(self.cfg["port"])
