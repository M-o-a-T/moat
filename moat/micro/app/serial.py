"""
Serial port access apps
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import AC_use
from moat.micro.part.serial import NamedSerial


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


_mode_d = dict(
    baudrate="int:baud (9600)",
    parity="bool|None:odd?",
    flow="str:RC for hardware",
    stopbits="int:1 or 2",
    bytesize="int: bits (8)",
    rts_state="bool:RTS on?",
    dtr_state="bool:DTR on?",
    rts_flip="bool:RTS flip on open?",
    dtr_flip="bool:DTR flip on open?",
    delay="float:wait after open",
    dtr_rts="float:wait between dtr and rts flip",
    delay_flip="float:wait after flip",
    flush="float|bool:flush inbuf after open (s, True=0.2)",
)
_cons_d = "bool|int:process non-framed data (default no; int=buflen)"
_frame_d = dict(
    max_idle="int:time between frames(ms)",
    max_packet="int:max len (127)",
    frame_start="int:start byte (xFA)",
    mark="int:each-framed-char marker (None)",
)
_loss_d = dict(
    _x="bool:enable w/ defaults",
    window="int:msgs in transit (8)",
    timeout="int:retransmit (ms)",
    retries="int:repeats until error(5)",
)
_link_d = dict(console=_cons_d, frame=_frame_d, lossy=_loss_d)


def Raw(*a, **k):
    """Sends/receives raw bytes off a serial port"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415

    class _Raw(BaseCmdBBM):
        doc = dict(_c=dict(_d="raw serial data", port="str:Port or 'USB'", mode=_mode_d))
        pack = None

        async def stream(self):
            return await AC_use(self, _KS(self.cfg))

    return _Raw(*a, **k)


def Msg(*a, **k):
    """snd/rcv: packetized data, via SerialPacker"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM  # noqa: PLC0415
    from moat.micro.proto._stream import SerialPackerBlkBuf  # noqa: PLC0415

    class _Msg(BaseCmdBBM):
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
            ser = SerialPackerBlkBuf(
                _KS(self.cfg),
                frame=self.cfg.get("frame", attrdict()),
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
        doc = dict(
            _c=dict(
                _d="message serial data",
                port="str:Port or 'USB'",
                mode=_mode_d,
                link=_link_d,
                log="str:log highlevel",
                log_rel="str:log lossy HL",
                log_raw="str:log lowlevel",
            )
        )

        async def stream(self):
            return await AC_use(self, console_stack(_KS(self.cfg), self.cfg))

    return _Link(*a, **k)
