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

    Config::

        c: 3  # pin# of control
        d: 4  # pin# of data
        cx: {}  # additional machine.Pin params for control pin
        dx: {}  # additional machine.Pin params for data pin
        f: 100000  # frequency, Hz
        s: false  # use bit-banging I²C driver?
        t: 500 # bus timeout, msec
    """
    _bus = None

    async def cmd_reset(self, p=None):  # noqa:ARG002
        # for _ in self._bus_cache.values():
        #     pass  # XXX b.close()
        self._bus_cache = dict()

    async def setup(self):
        """
        Open a bus.
        """
        await super().setup()
        self._setup()

    async def reload(self):
        self._teardown()
        self._setup()
        await super().reload()

    def _setup(self):
        c = machine.Pin(cfg["c"], **cfg.get("cx",{}))
        d = machine.Pin(cfg["d"], **cfg.get("dx",{}))
        self._bus = (machine.SoftI2C if cfg.get("soft",False) else machine.I2C)(
            scl=c,
            sda=d,
            freq=cfg.get(f, 100000),
            timeout=cfg.get("t", 1000) * 1000,
        )

    async def teardown(self):
        self._teardown()
        await super().teardown()

    def _teardown(self):
        if self._bus is None:
            try:
                self._bus.deinit()
            except AttributeError:
                pass


    async def cmd_rd(self, i, n=16):
        "read @n bytes from bus @cd at address @i"
        return self._bus.readfrom(i, n)

    async def cmd_wr(self, i, buf):
        "write @buf to bus @cd at address @i"
        return self._bus.writeto(i, buf)

    async def cmd_wrrd(self, i, buf, n=16):
        """
        write @buf to bus @cd at address @i, then read @n bytes.

        Returns -x if only x bytes could be written.
        """
        bus = self._bus
        d = self._bus.writeto(i, buf, False)
        if d < len(buf):
            bus.stop()
            return -d
        return self._bus.readfrom(i, n)

    async def cmd_scan(self):
        "scan the bus"
        return self._bus.scan()
