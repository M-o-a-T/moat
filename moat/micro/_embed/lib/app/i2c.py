"""
Access a satellite's i²c bus.
"""
from __future__ import annotations

try:
    import machine
except ImportError:
    from moat.micro._test import machine

from moat.micro.cmd.base import BaseCmd


class Cmd(BaseCmd):
    """
    This command implements basic access to an I²C bus.

    Warning: This is synchronous, thus subjects the whole system to
    arbitrary slowdowns if the destination device employs clock stretching.
    """

    _bus_cache = None  # c,d > busobj

    def __init__(self, cfg):
        super().__init__(cfg)
        self._bus_cache = dict()

    def _bus(self, cd, drop=False):
        # (c,d) > bus
        c, d = cd
        cd = (c, d)
        if drop:
            return self._bus_cache.pop(cd)
        else:
            return self._bus_cache[cd]

    def _del_cd(self, cd):
        self._bus(cd, True)

    async def cmd_reset(self, p=None):  # noqa:ARG002
        "close all"
        # for _ in self._bus_cache.values():
        #     pass  # XXX b.close()
        self._bus_cache = dict()

    async def cmd_open(self, c, d, cx={}, dx={}, f=1000000, t=1000000, s=False):  # noqa:B006
        """
        Open a bus.
        @c, @d: control and data pins.
        @cx, @dx: additional params for the pins.
        @f: clock frequency in Hz.
        @t: bus timeout in milliseconds.
        @s: flag: use software I²C driver?
        """
        cd = (c, d)
        if cd in self._bus_cache:
            pass  # close it
        c = machine.Pin(c, **cx)
        d = machine.Pin(d, **dx)
        bus = (machine.SoftI2C if s else machine.I2C)(scl=c, sda=d, freq=f, timeout=t * 1000)
        self._bus_cache[cd] = bus
        return cd

    async def cmd_rd(self, cd, i, n=16):
        "read @n bytes from bus @cd at address @i"
        bus = self._bus(cd)
        return bus.readfrom(i, n)

    async def cmd_wr(self, cd, i, buf):
        "write @buf to bus @cd at address @i"
        bus = self._bus(cd)
        return bus.writeto(i, buf)

    async def cmd_wrrd(self, cd, i, buf, n=16):
        "write @buf to bus @cd at address @i, then read @n bytes"
        bus = self._bus(cd)
        d = bus.writeto(i, buf, False)
        if d < len(buf):
            return -d
        return bus.readfrom(i, n)

    async def cmd_cl(self, cd):
        "close bus @cd"
        self._del_cd(cd)

    async def cmd_scan(self, cd):
        "scan bus @cd"
        bus = self._bus(cd)
        return bus.scan()
