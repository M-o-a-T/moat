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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.micro.console import Cmd


class StdioBuf(FileBuf):
    "direct access to stdio"

    async def stream(self):
        "Create a dedicated stdin/stdout stream"
        stdin = stdout = None
        try:
            stdin = open("/dev/stdin", "rb")  # noqa:SIM115,ASYNC230
            stdout = open("/dev/stdout", "wb")  # noqa:SIM115,ASYNC230
        except OSError:
            if stdin is not None:
                stdin.close()
            if stdout is not None:
                stdout.close()
            return sys.stdin.buffer, sys.stdout.buffer
        else:
            AC_use(self, stdin.close)
            AC_use(self, stdout.close)
            return stdin, stdout


class StdIO(BaseCmdMsg):
    """Sends/receives MoaT messages using stdin/stdout"""

    async def stream(self):
        "Set up a MoaT message stream on stdin+stdout"
        cs = StdioBuf(self.cfg)
        micropython.kbd_intr(-1)
        await AC_use(self, partial(micropython.kbd_intr, 3))
        return await AC_use(self, console_stack(cs, self.cfg))


def console(*a, **kw) -> Cmd:
    """Creates a 'real' Python console running the REPL"""
    from moat.micro.console import Cmd  # noqa:PLC0415

    return Cmd(*a, **kw)
