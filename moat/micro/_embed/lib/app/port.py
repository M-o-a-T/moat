import machine as M
from serialpacker import SerialPacker

from moat.util import import_
from moat.micro.cmd.stream import BaseBBMCmd


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
class Port(BaseBBMCmd):
    max_idle = 100
    pack = None

    @asynccontextmanager
    async def setup(self):
        intf = import_(self.cfg["device"])
        async with intf(self.cfg) as dev:
            try:
                self.dev = dev
            finally:
                self.dev = None
