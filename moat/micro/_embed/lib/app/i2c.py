"""
Access a satellite's i²c bus.
"""

from __future__ import annotations

from functools import partial

try:
    import machine
except ImportError:
    from moat.micro._test import machine

import contextlib

from moat.micro.cmd.base import BaseCmd
from moat.util.compat import Lock, to_thread

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable


class Cmd(BaseCmd):
    """
    This command implements basic access to an I²C bus.

    Warning: This is synchronous, thus subjects the whole system to
    arbitrary slowdowns if the destination device employs clock stretching.

    Config::

        id: None  # use soft i2c
        c: 3  # pin# of control
        d: 4  # pin# of data
        cx: {}  # additional machine.Pin params for control pin
        dx: {}  # additional machine.Pin params for data pin
        f: 100000  # frequency, Hz
        t: 1000 # bus timeout, msec
    """

    _bus = None

    async def setup(self):
        """
        Open a bus.
        """
        await super().setup()
        self._setup()

    async def reload(self):
        "reconfigured"
        self._teardown()
        self._setup()
        await super().reload()

    def _setup(self):
        cfg = self.cfg
        c = machine.Pin(cfg["c"], **cfg.get("cx", {}))
        d = machine.Pin(cfg["d"], **cfg.get("dx", {}))
        f = cfg.get("f", 100000)
        t = cfg.get("t", 1000) * 1000
        if (i := cfg.get("id", None)) is None:
            cls = machine.SoftI2C
        else:
            cls = partial(machine.I2C, i)
        self._bus = cls(scl=c, sda=d, freq=f, timeout=t)
        self.lock = Lock()

    async def teardown(self):
        "shutdown"
        self._teardown()
        await super().teardown()

    def _teardown(self):
        b, self._bus = self._bus, None
        if b is not None:
            with contextlib.suppress(AttributeError):
                b.deinit()

    doc_rd = dict(_d="read", _0="int:addr", n="int:nbytes(16)")

    async def cmd_rd(self, i, n=16):
        "read @n bytes from bus @cd at address @i"
        async with self.lock:
            return await to_thread(self._bus.readfrom, i, n)

    doc_wr = dict(_d="write", _0="int:addr", buf="bytes:data", _r="int:nbytes")

    async def cmd_wr(self, i, buf):
        "write @buf to bus @cd at address @i"
        async with self.lock:
            return await to_thread(self._bus.writeto, i, buf)

    doc_wrrd = dict(
        _d="write+read",
        _0="int:addr",
        buf="bytes:data",
        n="int:nbytes(16)",
        _r="int|bytes:nbytes short-written|read result",
    )

    async def cmd_wrrd(self, *a, **kw):
        """
        write @buf to bus @cd at address @i, then read @n bytes.

        Returns -x if only x bytes could be written.
        """
        async with self.lock:
            return await to_thread(self._cmd_wrrd, *a, **kw)

    def _cmd_wrrd(self, i, buf, n=16) -> Awaitable:
        bus = self._bus
        d = self._bus.writeto(i, buf, False)
        if d < len(buf):
            bus.stop()
            return d
        return self._bus.readfrom(i, n)

    doc_scan = dict(_d="bus scan")

    async def cmd_scan(self):
        "scan the bus"
        async with self.lock:
            return await to_thread(self._bus.scan)
