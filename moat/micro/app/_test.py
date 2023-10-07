"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro.cmd.stream import StreamCmd
from moat.micro._test import MpyBuf
from moat.micro.stacks.console import console_stack
from moat.micro.compat import AC_use


class MpyCmd(StreamCmd):
    """links to a local micropython process"""

    async def stream(self):
        mpy = MpyBuf(self.cfg)
        return await AC_use(self, console_stack(mpy, self.cfg))
