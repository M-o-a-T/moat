"""
Serial link app for MoaT message exchange.
"""

from __future__ import annotations

from moat.lib.micro import AC_use
from moat.lib.rpc.stream.cmdmsg import BaseCmdMsg
from moat.lib.stream import serial_stack
from moat.micro.app._doc import _link_d, _log_d, _mode_d

from ._util import get_serial


class Link(BaseCmdMsg):
    """r/w: exchange MoaT messages, possibly framed."""

    doc = dict(
        _c=dict(
            _d="message serial data",
            port="str:Port or 'USB'",
            mode=_mode_d,
            link=_link_d,
            **_log_d,
        )
    )

    async def stream(self):
        """Returns the console-stack-wrapped serial stream."""
        return await AC_use(self, serial_stack(get_serial(self.cfg), self.cfg))
