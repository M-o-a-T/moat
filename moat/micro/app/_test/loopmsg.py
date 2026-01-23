"""
Test Loopback connection app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.micro._test import LoopBBM
from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM


class LoopMsg(BaseCmdBBM):
    """Test Loopback connection.

    This app tests the LoopBBM back-end. Thus it needs to connect to a LoopLink
    that uses queues for both directions.
    """

    doc = dict(_c=dict(_d="Loopback test (RPC)"))

    async def stream(self):
        """Returns the loopback buffer."""
        return await AC_use(self, LoopBBM(self.cfg))
