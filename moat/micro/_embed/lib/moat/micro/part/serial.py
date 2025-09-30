"""
Adapter for MicroPython serial ports.
"""

from __future__ import annotations

import machine as M

from moat.util import import_
from moat.micro.stacks.file import FileBuf
from moat.util.compat import AC_use, TimeoutError, log, sleep, wait_for_ms  # noqa:A004


# Serial link driver
# cfg:
# uart: N
# tx: PIN
# rx: PIN
# baud: 9600
#
class NamedSerial(FileBuf):
    """
    Interface to a MicroPython serial port that's already open,
    via a module name.
    """

    def __init__(self, cfg):
        super().__init__(cfg=cfg, timeout=cfg.get("timeout", 50))

    async def stream(self):  # noqa: D102
        return import_(self.cfg["port"], 1)

    async def wr(self, buf):  # noqa: D102
        if len(buf) == 64:
            buf = memoryview(buf)
            await super().wr(buf[:32])
            await super().wr(buf[32:])
            return 64
        else:
            return await super().wr(buf)


class USBSerial(FileBuf):
    """
    Interface to a MicroPython serial port that's already open,
    via a module name.
    """

    async def stream(self):  # noqa: D102
        import moat  # noqa: PLC0415

        return moat.SERIAL


class Serial(NamedSerial):
    """
    Interface to a MicroPython serial port.
    """

    # inherits from NamedSerial for __init__ which is the same

    max_idle = 100
    pack = None

    async def stream(self):
        "opens the port, does flushing and RTS/CTS"
        pin_rts = pin_cts = pin_dtr = None
        cfg = self.cfg
        uart_cfg = {}
        p = cfg.get("mode", {})
        fl = p.get("flow", "")
        if "tx" in cfg:
            uart_cfg["tx"] = M.Pin(cfg["tx"], M.Pin.OUT)
        if "rx" in cfg:
            uart_cfg["rx"] = M.Pin(cfg["rx"])
        if "rts" in cfg:
            pin_rts = M.Pin(cfg["rts"], M.Pin.OUT)
            if "R" in fl:
                uart_cfg["rts"] = pin_rts
        if "cts" in cfg:
            pin_cts = M.Pin(cfg["cts"])
            if "C" in fl:
                uart_cfg["cts"] = pin_cts
        if "dtr" in cfg:
            pin_dtr = M.Pin(cfg["dtr"], M.Pin.OUT)
        uart_cfg["txbuf"] = cfg.get("txb", 128)
        uart_cfg["rxbuf"] = cfg.get("rxb", 128)

        uart_cfg["baudrate"] = p.get("rate", 9600)
        uart_cfg["parity"] = p.get("parity", None)
        uart_cfg["bits"] = p.get("bits", 8)
        f = 0
        if "C" in fl:
            f |= M.UART.CTS
        if "R" in fl:
            f |= M.UART.RTS
        uart_cfg["stop"] = p.get("stop", None) or 1  # no 1.5 stop bits

        rts = p.get("rts_state", 1)
        dtr = p.get("dtr_state", 1)
        dtr_rts = p.get("dtr_rts", 0)
        rts_flip = p.get("rts_flip", 0)
        dtr_flip = p.get("dtr_flip", 0)
        delay = p.get("delay", 0)
        delay_flip = p.get("delay_flip", 0.2)

        await sleep(delay)
        if rts_flip or dtr_flip:
            if dtr_rts >= 0:
                if pin_dtr is not None:
                    pin_dtr.value(dtr_flip ^ dtr)
                await sleep(dtr_rts)
                if pin_rts is not None:
                    pin_rts.value(rts_flip ^ rts)
            else:
                if pin_rts is not None:
                    pin_rts.value(rts_flip ^ rts)
                await sleep(-dtr_rts)
                if pin_dtr is not None:
                    pin_dtr.value(dtr_flip ^ dtr)
            await sleep(delay_flip)

        if dtr_rts > 0:
            if pin_dtr is not None:
                pin_dtr.value(dtr)
            await sleep(dtr_rts)
            if pin_rts is not None:
                pin_rts.value(rts)
        else:
            if pin_rts is not None:
                pin_rts.value(rts)
            await sleep(-dtr_rts)
            if pin_dtr is not None:
                pin_dtr.value(dtr)

        ser = M.UART(cfg.get("port", 0), **uart_cfg)
        ser.rts = rts
        ser.dtr = dtr
        await AC_use(self, ser.deinit)

        if t := cfg.get("flush"):
            if t is True:
                t = 200
            while True:
                buf = bytearray(32)
                try:
                    n = await wait_for_ms(t, ser.rd, buf)
                except TimeoutError:
                    break
                else:
                    log("Flush: %r", buf[:n])

        return ser
