"""
Raw TCP stream app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.lib.stream import TcpLink

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


class Raw(BaseCmdBBM):
    """Sends/receives raw data over TCP."""

    def stream(self) -> Awaitable:
        """Returns the TCP stream."""
        return AC_use(self, TcpLink(self.port))
