"""
Serial ports on Unix
"""
from __future__ import annotations

import anyio

from moat.micro.compat import AC_use, log
from moat.micro.proto.stream import AnyioBuf

from anyio_serial import Serial as _Serial


# Serial link driver
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
#
class Serial(AnyioBuf):
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
            if "R" not in fl or "C" not in fl:  # noqa:SIM102
                if "R" in fl or "C" in fl:
                    raise ValueError("no support for partial flow control")
            uart_cfg["rtscts"] = True
        uart_cfg["stopbits"] = p.get("stop", None) or 1  # no 1.5 stop bits
        uart_cfg["bytesize"] = p.get("bits", 8)

        rts = cfg.get("rts_state", 0)
        dtr = cfg.get("dtr_state", 0)
        rts_flip = cfg.get("rts_flip", 0)
        dtr_flip = cfg.get("dtr_flip", 0)

        ser = await AC_use(self, _Serial(**uart_cfg))
        if rts_flip or dtr_flip:
            ser.rts = rts_flip ^ rts
            ser.dtr = dtr_flip ^ dtr
            await anyio.sleep(0.2)
        ser.rts = rts
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
