"""
Remote port access apps
"""
from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.stream import BaseCmdBBM, BaseCmdMsg, BufCmd
from moat.micro.compat import AC_use
from moat.micro.stacks.console import console_stack

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Awaitable

    from most.micro.proto.stack import BaseBuf, BaseMsg

    from moat.micro.cmd.tree import SubDispatch


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

    sd: SubDispatch = None

    async def setup(self):
        "create a subdispatcher"
        await super().setup()
        self.sd = self.root.sub_at(*self.cfg["path"])

    def dispatch(self, action, msg, **kw) -> Awaitable:
        # pylint:disable=invalid-overridden-method
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
