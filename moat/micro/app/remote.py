"""
Remote port access apps
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.micro.stacks.console import console_stack

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.rpc import BaseCmd, SubMsgSender
    from moat.lib.stream import BaseBuf, BaseMsg
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

    from collections.abc import Awaitable


def Raw(*a, **k) -> BaseCmdBBM:
    """
    Link to a stream that's someplace else.

    This app forwards read/write requests to somewhere else.
    """
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415

    class _Raw(BaseCmdBBM):
        doc = dict(_c=dict(_d="Data forwarding", path="path:dest"))

        async def stream(self) -> BaseBuf:
            "returns the link"
            return await AC_use(self, self.root.sub_at(self.cfg["path"]))

    return _Raw(*a, **k)


def Fwd(*a, **k) -> BaseCmd:
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """
    from moat.lib.rpc import BaseCmd  # noqa: PLC0415

    class _Fwd(BaseCmd):
        sd: SubMsgSender = None

        doc = dict(_c=dict(_d="Command forwarding", path="path:dest"))

        async def setup(self):
            "create a subdispatcher"
            await super().setup()

            log = self.cfg.get("log", None)

            if not log:
                self.sd = self.root.sub_at(self.cfg["path"])
                return

            from moat.lib.rpc import MsgSender  # noqa: PLC0415
            from moat.lib.rpc._test import StreamLoop  # noqa: PLC0415

            a = StreamLoop(self.root, log + ">")
            b = StreamLoop(None, log + "<")
            a.attach_remote(b)
            b.attach_remote(a)
            await AC_use(self, a)
            xb = await AC_use(self, b)
            self.sd = MsgSender(xb)

        def handle(self, *a, **kw) -> Awaitable:
            # pylint:disable=invalid-overridden-method
            "call via the subdispatcher"
            return self.sd.handle(*a, **kw)

    return _Fwd(*a, **k)


def Link(*a, **k):
    """
    Connects to a `moat.micro.cmd.stream.cmdbbm.BaseCmdBBM` object
    exporting a `moat.lib.stream.BaseBuf`.
    """
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg  # noqa: PLC0415
    from moat.micro.cmd.stream.xcmd import BufCmd  # noqa: PLC0415

    class _Link(BaseCmdMsg):
        doc = dict(_c=dict(_d="Command forwarding to remote stream", path="path:dest"))

        async def stream(self) -> BaseMsg:
            "returns the stack-wrapped link"
            sd = BufCmd(self.cfg)
            return await AC_use(self, console_stack(sd, self.cfg))

    return _Link(*a, **k)
