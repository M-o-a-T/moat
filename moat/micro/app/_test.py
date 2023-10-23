"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro._test import Loopback, MpyBuf
from moat.micro.cmd.stream import BaseCmdBBM, BaseCmdMsg
from moat.micro.compat import AC_use
from moat.micro.proto.stream import MsgpackMsgBlk
from moat.micro.stacks.console import console_stack

from ._test_ import Cmd


class MpyCmd(BaseCmdMsg):
    """links to a local micropython process"""

    async def stream(self):
        mpy = MpyBuf(self.cfg)
        return await AC_use(self, console_stack(mpy, self.cfg))


class MpyRaw(BaseCmdBBM):
    """links to a local micropython process"""

    async def stream(self):
        return await AC_use(self, MpyBuf(self.cfg))


class Loop(BaseCmdMsg):
    async def stream(self):
        s = Loopback(**self.cfg.get("loop", {}))
        s.link(s)
        if (li := self.cfg.get("link", None)) is not None:
            if "pack" in li and len(li) == 1:
                s = await AC_use(self, MsgpackMsgBlk(s, li))
            else:
                s = await AC_use(self, console_stack(s, self.cfg))
        return s
