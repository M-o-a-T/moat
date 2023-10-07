"""
Console stdio access
"""

from __future__ import annotations

import sys
from functools import partial

from moat.micro.cmd.stream import StreamCmd
from moat.micro.stacks.console import console_stack
from moat.micro.part.serial import Serial
from moat.micro.proto.stream import FileBuf
from moat.micro.compat import AC_use
import micropython

class StdioBuf(FileBuf):
    async def stream(self):
        return sys.stdin.buffer,sys.stdout.buffer

class StdIO(StreamCmd):
    """Sends/receives MoaT messages using stdin/stdout"""

    async def stream(self):
        cs = StdioBuf(self.cfg)
        micropython.kbd_intr(-1)
        await AC_use(self, partial(micropython.kbd_intr, 3))
        return await AC_use(self, console_stack(cs, self.cfg))
