"""
Serial port access apps
"""
from __future__ import annotations

from moat.micro.compat import AC_use
from moat.micro.cmd.stream import BaseBBMCmd, StreamCmd
from moat.micro.stacks.console import console_stack
from moat.micro.part.serial import Serial


# Serial packet forwarder
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
# max:
#   len: N
#   idle: MSEC
# start: NUM
#
class Raw(BaseBBMCmd):
    max_idle = 100
    pack = None

    async def setup(self):
        return await AC_use(self, Serial(self.cfg))


class Link(StreamCmd):
    """Sends/receives MoaT messages using some device"""
    async def stream(self):
        return await AC_use(self, console_stack(Serial(self.cfg), self.cfg))

