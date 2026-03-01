"""
Access a satellite's i²c bus.
"""

from __future__ import annotations

from smbus3 import SMBus, i2c_msg

from moat.lib.micro import Lock, to_thread
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg

    from typing import Any, Protocol

    class _I2CWriteRes(Protocol):
        len: int


class Cmd(BaseCmd):
    r"""
    This command implements basic access to an I²C bus.

    Parameters::

        id: bus ID (no soft i2c here)
        \# f: 100000  \# frequency, Hz
        t: 1000 \# bus timeout, msec
    """

    doc = dict(
        c=dict(
            _d="i²c bus read/write/dir",
            t="int:timeout(ms)",
            id="int:bus#",
        )
    )

    _bus: SMBus

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._lock = Lock()

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
        try:
            b = self._bus
        except AttributeError:
            return
        del self._bus
        b.close()

    doc_rd = dict(_d="read", _0="int:addr", n="int:nbytes(16)")

    async def cmd_rd(self, i, n=16) -> bytes:
        "read @n bytes from bus @cd at address @i"
        return bytes(self._bus.i2c_rd(i, n))

    doc_wr = dict(_d="write", _0="int:addr", buf="bytes:data", _r="int:nbytes")

    async def cmd_wr(self, i: int, buf: bytes) -> int:
        "write @buf to bus @cd at address @i"
        async with self._lock:
            res = cast("_I2CWriteRes", await to_thread(self._bus.i2c_wr, i, list(buf)))
            return res.len

    doc_wrrd = dict(
        _d="write+read",
        _0="int:addr",
        buf="bytes:data",
        n="int:nbytes(16)",
        _r="int|bytes:nbytes short-written|read result",
    )

    async def cmd_wrrd(self, i, buf, n=16) -> bytes:
        """
        write @buf to bus @cd at address @i, then read @n bytes.

        Returns -x if only x bytes could be written.
        """

        def _run():
            wr = i2c_msg.write(i, list(buf))
            rd = i2c_msg.read(i, n)

            self._bus.i2c_rdwr(wr, rd)
            return rd

        async with self._lock:
            rd = await to_thread(_run)
        return bytes(rd)

    doc_scan = dict(_d="bus scan")

    async def cmd_scan(self) -> list[int]:
        """
        Scan the bus.

        Returns: the list of working addresses.
        """
        bus = self._bus
        res = []
        for i in range(0x08, 0x78):
            try:
                if i >> 4 in (3, 5):
                    await to_thread(bus.read_byte, i)
                else:
                    await to_thread(bus.write_quick, i)
            except OSError:
                pass
            else:
                res.append(i)
        return res

    async def handle(self, msg: Msg, rcmd: list[PathElem]) -> Any:
        """
        Intercept the bus address: ``bus:33.wr(x)`` ≍ ``bus.wr(33,x)``.
        """
        if rcmd and isinstance(rcmd[-1], int):
            msg.args_l.insert(0, rcmd.pop())
        return await super().handle(msg, rcmd)
