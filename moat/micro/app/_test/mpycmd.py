"""
MoaT link to a local micropython process.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdmsg import BaseCmdMsg
from moat.micro._test import MpyBuf
from moat.micro.stacks.console import console_stack


class MpyCmd(BaseCmdMsg):
    """MoaT link to a local micropython process."""

    doc = dict(_c=dict(_d="RPC to MicroPython"))

    async def stream(self):
        """Returns the console-stack-wrapped micropython buffer."""
        mpy = MpyBuf(self.cfg)
        return await AC_use(self, console_stack(mpy, self.cfg))
