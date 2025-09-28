"""
Serial ports on Unix
"""

from __future__ import annotations

import anyio

from anyio_serial import Serial as _Serial

from moat.micro.proto.stream import AnyioBuf
from moat.util.compat import AC_use, log


# Serial link driver
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
#
class Serial(AnyioBuf):
    """
    We don't have numbered serial ports on Unix.
    """

    def __init__(self, *a, **k):
        raise NotImplementedError("Use NamedSerial on Unix")


class NamedSerial(AnyioBuf):
    """
    Serial port abstraction.
    """

    max_idle = 100
    pack = None

    async def stream(self):  # noqa:D102
        cfg = self.cfg
        uart_cfg = {}
        uart_cfg["port"] = cfg["port"]

        p = cfg.get("mode", {})

        uart_cfg["baudrate"] = p.get("rate", 9600)
        pa = p.get("parity", None)
        if pa:
            pa = "O"
        elif pa is not None:
            pa = "E"
        else:
            pa = "N"
        uart_cfg["parity"] = pa

        fl = p.get("flow", None)
        if fl:
            if "R" not in fl or "C" not in fl:
                if "R" in fl or "C" in fl:
                    raise ValueError("no support for partial flow control")
            uart_cfg["rtscts"] = True
        uart_cfg["stopbits"] = p.get("stop", None) or 1  # no 1.5 stop bits
        uart_cfg["bytesize"] = p.get("bits", 8)

        rts = p.get("rts_state", 1)
        dtr = p.get("dtr_state", 1)
        dtr = p.get("dtr_state", 1)
        dtr_rts = p.get("dtr_rts", 0)
        rts_flip = p.get("rts_flip", 0)
        dtr_flip = p.get("dtr_flip", 0)
        delay = p.get("delay", 0)
        delay_flip = p.get("delay_flip", 0.2)

        ser = await AC_use(self, _Serial(**uart_cfg))
        await anyio.sleep(delay)
        if rts_flip or dtr_flip:
            if dtr_rts >= 0:
                ser.dtr = dtr_flip ^ dtr
                await anyio.sleep(dtr_rts)
                ser.rts = rts_flip ^ rts
            else:
                ser.rts = rts_flip ^ rts
                await anyio.sleep(-dtr_rts)
                ser.dtr = dtr_flip ^ dtr
            await anyio.sleep(delay_flip)
        if dtr_rts > 0:
            ser.dtr = dtr
            await anyio.sleep(dtr_rts)
            ser.rts = rts
        else:
            ser.rts = rts
            await anyio.sleep(-dtr_rts)
            ser.dtr = dtr

        # flush messages
        if t := cfg.get("flush"):
            if t is True:
                t = 0.2
            else:
                t /= 1000
            while True:
                with anyio.move_on_after(t):
                    res = await ser.receive(200)
                    log("Flush: %r", res)
                    continue
                break
        return ser
