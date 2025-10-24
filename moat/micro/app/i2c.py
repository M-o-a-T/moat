"""
Access a satellite's i²c bus.
"""

from __future__ import annotations

from smbus3 import SMBus, i2c_msg

from moat.micro.cmd.base import BaseCmd


class Cmd(BaseCmd):
    """
    This command implements basic access to an I²C bus.

    Warning: This is synchronous, thus subjects the whole system to
    arbitrary slowdowns if the destination device employs clock stretching.

    Config::

        id: bus ID (no soft i2c here)
        # f: 100000  # frequency, Hz
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
        # f = cfg.get("f", 100000)
        t = cfg.get("t", 1000) * 1000
        self._bus = b = SMBus(cfg.id)
        b.set_timeout(int(t * 100))

    async def teardown(self):
        "shutdown"
        self._teardown()
        await super().teardown()

    def _teardown(self):
        b, self._bus = self._bus, None
        if b is not None:
            b.close()

    doc_rd = dict(_d="read", _0="int:addr", n="int:nbytes(16)")

    async def cmd_rd(self, i, n=16):
        "read @n bytes from bus @cd at address @i"
        return bytes(self._bus.i2c_rd(i, n))

    doc_wr = dict(_d="write", _0="int:addr", buf="bytes:data", _r="int:nbytes")

    async def cmd_wr(self, i: int, buf: bytes):
        "write @buf to bus @cd at address @i"
        return self._bus.i2c_wr(i, list(buf)).len

    doc_wrrd = dict(
        _d="write+read",
        _0="int:addr",
        buf="bytes:data",
        n="int:nbytes(16)",
        _r="int|bytes:nbytes short-written|read result",
    )

    async def cmd_wrrd(self, i, buf, n=16):
        """
        write @buf to bus @cd at address @i, then read @n bytes.

        Returns -x if only x bytes could be written.
        """
        bus = self._bus
        wr = i2c_msg.write(i, list(buf))
        rd = i2c_msg.read(i, n)

        bus.i2c_rdwr(wr, rd)
        return bytes(rd)

    doc_scan = dict(_d="bus scan")

    async def cmd_scan(self):
        "scan the bus"
        res = []
        for i in range(0x08, 0x78):
            try:
                if i >> 4 in (3, 5):
                    self._bus.read_byte(i)
                else:
                    self._bus.write_quick(i)
            except OSError:
                pass
            else:
                res.append(i)
        return res
