"""
Serial port access apps
"""
from __future__ import annotations

from contextlib import asynccontextmanager

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

    @asynccontextmanager
    async def setup(self):
        async with Serial(self.cfg) as dev:
            yield dev


class Link(StreamCmd):
    """Sends/receives MoaT messages"""
    @asynccontextmanager
    async def stream(self):
        async with console_stack(Serial(self.cfg), self.cfg) as stream:
            yield stream
