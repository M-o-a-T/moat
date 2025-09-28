"""
Console stdio access
"""

from __future__ import annotations

import sys
from functools import partial

import micropython

from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.stacks.console import console_stack
from moat.micro.stacks.file import FileBuf
from moat.util.compat import AC_use


class StdioBuf(FileBuf):
    "direct access to stdio"

    async def stream(self):  # noqa:D102
        return sys.stdin.buffer, sys.stdout.buffer


class StdIO(BaseCmdMsg):
    """Sends/receives MoaT messages using stdin/stdout"""

    async def stream(self):  # noqa:D102
        cs = StdioBuf(self.cfg)
        micropython.kbd_intr(-1)
        await AC_use(self, partial(micropython.kbd_intr, 3))
        return await AC_use(self, console_stack(cs, self.cfg))
