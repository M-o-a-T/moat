"""
Access any moat.micro Buf/Blk/Msg device
"""

from __future__ import annotations

from moat.util import import_
from moat.micro.cmd.stream import BaseCmdBBM
from moat.util.compat import AC_use


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
class Port(BaseCmdBBM):
    """
    Access any moat.micro Buf/Blk/Msg device.

    The config item "device" must contain the class path.
    """

    max_idle = 100
    pack = None

    async def stream(self):
        "setup,"
        intf = import_(self.cfg["device"])
        return await AC_use(self, intf(self.cfg))
