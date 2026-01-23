"""
Raw Unix socket stream app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.stream import UnixLink
from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


class Raw(BaseCmdBBM):
    """Sends/receives raw data over a Unix socket."""

    def stream(self) -> Awaitable:
        """Returns the Unix socket stream."""
        return AC_use(self, UnixLink(self.port, retry=self.cfg.get("retry", attrdict())))
