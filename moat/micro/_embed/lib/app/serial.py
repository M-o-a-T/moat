"""
Serial port access apps
"""
from __future__ import annotations

from moat.micro.compat import AC_use
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
def Raw(*a, **k):
    """Sends/receives raw bytes off a serial port"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM

    class _Raw(BaseCmdBBM):
        max_idle = 100
        pack = None

        async def stream(self):
            return await AC_use(self, Serial(self.cfg))

    return _Raw(*a, **k)


def Msg(*a, **k):
    """snd/rcv: packetized data, via SerialPacker"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM
    from moat.micro.cmd.proto.stream import SerialPackerBlkBuf

    class _Msg(BaseCmdBBM):
        async def stream(self):
            ser = SerialPackerBlkBuf(Serial(self.cfg), frame=self.cfg.get("frame",{}), cons=self.cfg.get("console", ))
            return await AC_use(self, BaseCmdBBM(ser))

    return _Msg(*a, **k)


def Link(*a, **k):
    """r/w: exchange MoaT messages, possibly framed"""
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
    from moat.micro.stacks.console import console_stack

    class _Link(BaseCmdMsg):
        async def stream(self):
            return await AC_use(self, console_stack(Serial(self.cfg), self.cfg))

    return _Link(*a, **k)
