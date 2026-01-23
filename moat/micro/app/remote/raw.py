"""
Raw remote stream forwarding app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.stream import BaseBuf


class Raw(BaseCmdBBM):
    """
    Link to a stream that's someplace else.

    This app forwards read/write requests to somewhere else.
    """

    doc = dict(_c=dict(_d="Data forwarding", path="path:dest"))

    async def stream(self) -> BaseBuf:
        """Returns the link."""
        return await AC_use(self, self.root.sub_at(self.cfg["path"]))
