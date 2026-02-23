"""
Docstrings for mode and serial
"""

from __future__ import annotations

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

_log_d = dict(log="str:log highlevel", log_rel="str:log lossy HL", log_raw="str:log lowlevel")
