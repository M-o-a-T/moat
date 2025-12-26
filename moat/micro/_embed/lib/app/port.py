"""
Access any moat.micro Buf/Blk/Msg device
"""

from __future__ import annotations

from moat.util import import_
from moat.lib.micro import AC_use
from moat.micro.cmd.stream import BaseCmdBBM


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

    pack = None

    async def stream(self):
        "setup,"
        intf = import_(self.cfg["device"])
        return await AC_use(self, intf(self.cfg))
