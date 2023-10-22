"""
Remote port access apps
"""
from __future__ import annotations

from moat.micro.compat import AC_use
from moat.micro.cmd.stream import BaseCmdBBM, BufCmd, BaseCmdMsg
from moat.micro.cmd.base import BaseCmd
from moat.micro.stacks.console import console_stack
from moat.micro.part.serial import Serial

class Raw(BaseCmdBBM):
    """
    Link to a stream that's someplace else.

    This app forwards read/write requests to somewhere else.
    """
    async def stream(self) -> BaseBuf:
        "returns the link"
        return await AC_use(self, self.root.sub_at(*self.cfg["path"]))


class Fwd(BaseCmd):
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """
    async def setup(self):
        "create a subdispatcher"
        await super().setup()
        self.sd = self.root.sub_at(*self.cfg["path"])

    def dispatch(self, action, msg, **kw) -> Awaitable:
        "call via the subdispatcher"
        return self.sd.dispatch(action, msg, **kw)


class Link(BaseCmdMsg):
    """
    Connects to a `BaseCmdBBM` object exporting a `BaseBuf`.

    
    """
    async def stream(self) -> BaseMsg:
        "returns the stack-wrapped link"
        sd = BufCmd(self.cfg)
        return await AC_use(self, console_stack(sd, self.cfg))

