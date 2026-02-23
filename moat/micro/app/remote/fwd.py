"""
Remote command forwarding app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.rpc import SubMsgSender

    from collections.abc import Awaitable


class Fwd(BaseCmd):
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """

    sd: SubMsgSender = None

    doc = dict(_c=dict(_d="Command forwarding", path="path:dest"))

    async def setup(self):
        """Create a subdispatcher."""
        await super().setup()

        log = self.cfg.get("log", None)

        if not log:
            self.sd = self.root.sub_at(self.cfg["path"])
            return

        from moat.lib.rpc import MsgSender  # noqa: PLC0415
        from moat.lib.rpc.loop import StreamLoop  # noqa: PLC0415

        a = StreamLoop(self.root, log + ">")
        b = StreamLoop(None, log + "<")
        a.attach_remote(b)
        b.attach_remote(a)
        await AC_use(self, a)
        xb = await AC_use(self, b)
        self.sd = MsgSender(xb)

    def handle(self, *a, **kw) -> Awaitable:
        """Call via the subdispatcher."""
        return self.sd.handle(*a, **kw)
