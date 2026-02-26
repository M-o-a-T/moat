"""
Raw TCP stream app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.lib.stream import TcpLink

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.stream import BaseBuf


class Raw(BaseCmdBBM):
    """Sends/receives raw data over TCP."""

    async def stream(self) -> BaseBuf:
        """Returns the TCP stream."""
        return await AC_use(
            self,
            TcpLink(
                self.cfg.get("host", "127.0.0.1"),
                self.cfg["port"],
                retry=self.cfg.get("retry", attrdict()),
            ),
        )
