"""
Serial port access apps
"""

from __future__ import annotations

from moat.micro.part.serial import NamedSerial
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
def _KS(cfg):
    p = cfg["port"]
    if not isinstance(p, str):
        pass
    elif p == "USB":
        from moat.micro.part.serial import USBSerial  # noqa: PLC0415

        Ser = USBSerial
    else:
        Ser = NamedSerial
    return Ser(cfg)


def Raw(*a, **k):
    """Sends/receives raw bytes off a serial port"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415

    class _Raw(BaseCmdBBM):
        max_idle = 100
        pack = None

        async def stream(self):
            return await AC_use(self, _KS(self.cfg))

    return _Raw(*a, **k)


def Msg(*a, **k):
    """snd/rcv: packetized data, via SerialPacker"""
    from moat.micro.cmd.proto.stream import SerialPackerBlkBuf  # noqa: PLC0415
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415

    class _Msg(BaseCmdBBM):
        async def stream(self):
            ser = SerialPackerBlkBuf(
                _KS(self.cfg),
                frame=self.cfg.get("frame", {}),
                cons=self.cfg.get(
                    "console",
                ),
            )
            return await AC_use(self, BaseCmdBBM(ser))

    return _Msg(*a, **k)


def Link(*a, **k):
    """r/w: exchange MoaT messages, possibly framed"""
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg  # noqa: PLC0415
    from moat.micro.stacks.console import console_stack  # noqa: PLC0415

    class _Link(BaseCmdMsg):
        async def stream(self):
            return await AC_use(self, console_stack(_KS(self.cfg), self.cfg))

    return _Link(*a, **k)
