"""
Raw stdio of a local micropython process.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.micro._test import MpyBuf


class MpyRaw(BaseCmdBBM):
    """stdio of a local micropython process."""

    doc = dict(_c=dict(_d="Data to MicroPython"))

    async def stream(self):
        """Returns the micropython buffer."""
        return await AC_use(self, MpyBuf(self.cfg))
