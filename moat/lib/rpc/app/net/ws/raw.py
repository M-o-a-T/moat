"""
Raw websocket stream app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.lib.stream import WsLink

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from types import CoroutineType

    from moat.lib.stream import BaseBlk

    from typing import Any


class Raw(BaseCmdBBM):
    """Sends/receives raw websocket blocks."""

    def stream(self) -> CoroutineType[Any, Any, BaseBlk]:
        """Returns the websocket block stream."""
        path = self.cfg.get("path", "/")
        if not path.startswith("/"):
            path = "/" + path
        url = self.cfg.get(
            "url",
            "{}://{}:{}{}".format(
                "wss" if self.cfg.get("ssl", False) else "ws",
                self.cfg.get("host", "127.0.0.1"),
                self.cfg["port"],
                path,
            ),
        )
        return AC_use(
            self,
            WsLink(
                url,
                retry=self.cfg.get("retry", attrdict()),
                subprotocols=self.cfg.get("subprotocols", None),
            ),
        )
