"""
Remote command forwarding app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import MsgHandler, MsgSender
    from moat.lib.rpc.msg import Msg


class Fwd(BaseCmd):
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """

    sd: MsgSender | None = None

    doc = dict(_c=dict(_d="Command forwarding", path="path:dest"))

    async def setup(self):
        """Create a subdispatcher."""
        await super().setup()

        log = self.cfg.get("log", None)
        root = self.root
        if root is None:
            raise RuntimeError("Not attached")

        if not log:
            self.sd = cast("MsgSender", root.sub_at(self.cfg["path"]))
            return

        from moat.lib.rpc import MsgSender  # noqa: PLC0415
        from moat.lib.rpc.loop import StreamLoop  # noqa: PLC0415

        a = StreamLoop(cast("MsgHandler", root), log + ">")
        b = StreamLoop(None, log + "<")
        a.attach_remote(b)
        b.attach_remote(a)
        await AC_use(self, a)
        xb = await AC_use(self, b)
        self.sd = MsgSender(xb)

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: str):
        """Call via the subdispatcher."""
        sd = self.sd
        if sd is None:
            raise RuntimeError("Not ready")
        return await sd.handle(msg, rcmd, *prefix)
