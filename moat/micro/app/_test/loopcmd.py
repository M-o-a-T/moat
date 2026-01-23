"""
Full-stack loopback test app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.stream import CBORMsgBlk
from moat.micro._test import Loopback
from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
from moat.micro.stacks.console import console_stack


class LoopCmd(BaseCmdMsg):
    """Full-stack Loopback. This goes through CBOR."""

    doc = dict(_c=dict(_d="Loopback test (RPC+CBOR)"))

    async def stream(self):
        """Returns the loopback stream."""
        # accepts qlen and loss
        s = Loopback(**self.cfg.get("loop", attrdict()))
        s.link(s)
        if (li := self.cfg.get("link", None)) is not None:
            if "pack" in li and len(li) == 1:
                s = CBORMsgBlk(s, li)
                if (log := self.cfg.get("log", None)) is not None:
                    from moat.lib.stream import LogMsg  # noqa: PLC0415

                    s = LogMsg(s, log)
                s = await AC_use(self, s)
            else:
                s = await AC_use(self, console_stack(s, self.cfg))
        return s
