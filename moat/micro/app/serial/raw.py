"""
Raw serial port app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.micro.app._doc import _mode_d

from ._util import get_serial


class Raw(BaseCmdBBM):
    """Sends/receives raw bytes off a serial port."""

    doc = dict(_c=dict(_d="raw serial data", port="str:Port or 'USB'", mode=_mode_d))
    pack = None

    async def stream(self):
        """Returns the serial stream."""
        return await AC_use(self, get_serial(self.cfg))
