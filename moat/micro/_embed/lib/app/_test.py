"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro.cmd.base import BaseCmd

class Cmd(BaseCmd):
    async def cmd_echo(self, m:Any):
        return {'r':m}
