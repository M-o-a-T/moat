"""
Remote command forwarding app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from types import CoroutineType

    from moat.lib.path import PathElem
    from moat.lib.rpc import MsgSender
    from moat.lib.rpc.msg import Msg

    from typing import Any


class Fwd(BaseCmd):
    """
    Link to a stream that's someplace else.

    This app forwards to somewhere else.
    """

    sd: MsgSender

    doc = dict(_c=dict(_d="Command forwarding", path="path:dest"))

    async def setup(self):
        """Create a subdispatcher."""
        await super().setup()

        log = self.cfg.get("log", None)
        root = self.root
        if root is None:
            raise RuntimeError("Not attached")

        if not log:
            self.sd = root.sub_at(self.cfg["path"])
            return

        from moat.lib.rpc import MsgSender  # noqa: PLC0415
        from moat.lib.rpc.loop import StreamLoop  # noqa: PLC0415

        a = StreamLoop(root, log + ">")
        b = StreamLoop(None, log + "<")
        a.attach_remote(b)
        b.attach_remote(a)
        await AC_use(self, a)
        xb = await AC_use(self, b)
        self.sd = MsgSender(xb)

    def handle(self, msg: Msg, rcmd: list[PathElem]) -> CoroutineType[Any, Any, None]:
        """Call via the subdispatcher."""
        return self.sd.handle(msg, rcmd)
