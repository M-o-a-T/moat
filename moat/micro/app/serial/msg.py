"""
Packetized serial port app.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.lib.stream._serial import SerialPackerBlkBuf
from moat.micro.app._doc import _cons_d, _frame_d, _mode_d
from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

from ._util import get_serial


class Msg(BaseCmdBBM):
    """snd/rcv: packetized data, via SerialPacker."""

    doc = dict(
        _c=dict(
            _d="packet serial data",
            port="str:Port or 'USB'",
            mode=_mode_d,
            frame=_frame_d,
            cons=_cons_d,
        )
    )

    async def stream(self):
        """Returns the packetized serial stream."""
        ser = SerialPackerBlkBuf(
            get_serial(self.cfg),
            frame=self.cfg.get("frame", attrdict()),
            cons=self.cfg.get(
                "console",
            ),
        )
        return await AC_use(self, BaseCmdBBM(ser))
