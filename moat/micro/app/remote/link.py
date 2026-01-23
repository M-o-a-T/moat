"""
Remote link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.cmd.stream.xcmd import BufCmd
from moat.micro.stacks.console import console_stack

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.stream import BaseMsg


class Link(BaseCmdMsg):
    """
    Connects to a `moat.micro.cmd.stream.cmdbbm.BaseCmdBBM` object
    exporting a `moat.lib.stream.BaseBuf`.
    """

    doc = dict(_c=dict(_d="Command forwarding to remote stream", path="path:dest"))

    async def stream(self) -> BaseMsg:
        """Returns the stack-wrapped link."""
        sd = BufCmd(self.cfg)
        return await AC_use(self, console_stack(sd, self.cfg))
