"""
Raw remote stream forwarding app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM

from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from moat.lib.rpc import MsgSender
    from moat.lib.stream import BaseBuf


class Raw(BaseCmdBBM):
    """
    Link to a stream that's someplace else.

    This app forwards read/write requests to somewhere else.
    """

    doc = dict(_c=dict(_d="Data forwarding", path="path:dest"))

    async def stream(self) -> BaseBuf:
        """Returns the link."""
        root = self.root
        if root is None:
            raise RuntimeError("Not attached")
        return cast(
            "BaseBuf",
            await AC_use(self, cast("MsgSender", root.sub_at(self.cfg["path"]))),
        )
