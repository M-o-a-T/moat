"""
Console stdio access
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.stream import FilenoBuf
from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.stacks.console import console_stack


class StdIO(BaseCmdMsg):
    """Sends/receives MoaT messages using stdin/stdout"""

    async def stream(self):  # noqa:D102
        cs = FilenoBuf(self.cfg)
        return await AC_use(self, console_stack(cs, self.cfg))
