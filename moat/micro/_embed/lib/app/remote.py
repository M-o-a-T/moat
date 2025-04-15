"""
Remote port access apps
"""

from __future__ import annotations

from moat.util.compat import AC_use
from moat.micro.stacks.console import console_stack

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from moat.micro.cmd.tree.dir import SubDispatch

    from most.micro.proto.stack import BaseBuf, BaseMsg


def Raw(*a, **k):
    """
    Link to a stream that's someplace else.

    This app forwards read/write requests to somewhere else.
    """
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

    class _Raw(BaseCmdBBM):
        async def stream(self) -> BaseBuf:
            "returns the link"
            return await AC_use(self, self.root.sub_at(self.cfg["path"]))

    return _Raw(*a, **k)


def Fwd(*a, **k):
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """
    from moat.micro.cmd.base import BaseCmd

    class _Fwd(BaseCmd):
        sd: SubDispatch = None

        async def setup(self):
            "create a subdispatcher"
            await super().setup()

            log = self.cfg.get("log", None)

            if not log:
                self.sd = self.root.sub_at(self.cfg["path"])
                return

            from moat.lib.cmd._test import StreamLoop
            from moat.lib.cmd.base import MsgSender

            a = StreamLoop(self.root, log + ">")
            b = StreamLoop(None, log + "<")
            a.attach_remote(b)
            b.attach_remote(a)
            xa = await AC_use(self, a)
            xb = await AC_use(self, b)
            self.sd = MsgSender(xb)

        def handle(self, *a, **kw) -> Awaitable:
            # pylint:disable=invalid-overridden-method
            "call via the subdispatcher"
            return self.sd.handle(*a, **kw)

    return _Fwd(*a, **k)


def Link(*a, **k):
    """
    Connects to a `BaseCmdBBM` object exporting a `BaseBuf`.
    """
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
    from moat.micro.cmd.stream.xcmd import BufCmd

    class _Link(BaseCmdMsg):
        async def stream(self) -> BaseMsg:
            "returns the stack-wrapped link"
            sd = BufCmd(self.cfg)
            return await AC_use(self, console_stack(sd, self.cfg))

    return _Link(*a, **k)
