"""
Raw serial port app.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdbbm import BaseCmdBBM
from moat.micro.app._doc import _mode_d

from ._util import get_serial

from typing import TYPE_CHECKING as _TC

if _TC:
    from typing import Any


class Raw(BaseCmdBBM):
    """Sends/receives raw bytes off a serial port."""

    doc = dict(_c=dict(_d="raw serial data", port="str:Port or 'USB'", mode=_mode_d))
    pack = None

    async def stream(self) -> Any:
        """Returns the serial stream."""
        return await AC_use(self, get_serial(self.cfg))
