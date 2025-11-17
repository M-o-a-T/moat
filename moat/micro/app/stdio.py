"""
Console stdio access
"""

from __future__ import annotations

from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.proto.stream.py import FilenoBuf
from moat.micro.stacks.console import console_stack
from moat.util.compat import AC_use


class StdIO(BaseCmdMsg):
    """Sends/receives MoaT messages using stdin/stdout"""

    async def stream(self):  # noqa:D102
        cs = FilenoBuf(self.cfg)
        return await AC_use(self, console_stack(cs, self.cfg))
