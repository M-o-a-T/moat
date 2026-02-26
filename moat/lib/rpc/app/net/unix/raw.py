"""
Raw Unix socket stream app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.lib.stream import UnixLink

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.stream import BaseBuf
    from types import CoroutineType
    from typing import Any


class Raw(BaseCmdBBM):
    """Sends/receives raw data over a Unix socket."""

    def stream(self) -> CoroutineType[Any,Any,BaseBuf]:
        """Returns the Unix socket stream."""
        return AC_use(
            self,
            UnixLink(self.cfg["port"], retry=self.cfg.get("retry", attrdict())),
        )
