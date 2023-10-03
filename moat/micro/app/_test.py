"""

"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd
from moat.micro._test import MpyBuf
from moat.micro.stacks.console import console_stack
from moat.micro.compat import AC_use


class MpyCmd(StreamCmd):
    """starts a local micropython process"""
    def __init__(self, cfg, cff="test"):
        super().__init__(cfg)
        self.temp = temp
        self.cfg = cfg
        self.cff = cff

    async def stream(self):
        mpy = MpyBuf(self.cfg,self.temp,cff=self.cff)
        return await AC_use(self, async with console_stack(mpy))


class Cmd(BaseCmd):
    async def cmd_echo(self, m):
        return {'r':m}
