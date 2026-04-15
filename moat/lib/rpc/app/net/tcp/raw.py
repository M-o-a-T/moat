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
    from types import CoroutineType

    from moat.lib.stream import BaseBuf

    from typing import Any


class Raw(BaseCmdBBM):
    """Sends/receives raw data over TCP."""

    def stream(self) -> CoroutineType[Any, Any, BaseBuf]:
        """Returns the TCP stream."""
        return AC_use(
            self,
            TcpLink(
                self.cfg.get("host", "127.0.0.1"),
                self.cfg["port"],
                retry=self.cfg.get("retry", attrdict()),
            ),
        )
