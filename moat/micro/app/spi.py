"""
Access a satellite's SPI bus (Linux/CPython version using spidev).
"""

from __future__ import annotations

import spidev

from moat.lib.micro import Lock, to_thread
from moat.lib.rpc import BaseCmd

# Per-bus locks to prevent concurrent access
_bus_locks: dict[tuple[int, int], Lock] = {}


def _get_bus_lock(bus: int, device: int) -> Lock:
    """Get or create a lock for the given bus/device."""
    key = (bus, device)
    if key not in _bus_locks:
        _bus_locks[key] = Lock()
    return _bus_locks[key]


class Cmd(BaseCmd):
    """
    This command implements basic access to a SPI bus on Linux.

    Config::

        bus: 0      # SPI bus number
        dev: 0      # SPI device number (directly controls CS)
        f: 1000000  # frequency, Hz (max_speed_hz)
        mode: 0     # SPI mode (0-3, combines polarity and phase)
        bits: 8     # bits per word

    On Linux, CS is controlled by the kernel driver based on the device number,
    so no separate CS path is needed.
    """

    _spi = None

    doc = dict(
        _c=dict(_d="SPI driver (Linux)"),
        bus="int:bus number",
        dev="int:device number",
        f="int:frequency",
        mode="int:SPI mode(0-3)",
        bits="int:bits per word(8)",
    )

    def __init__(self, cfg: dict):
        super().__init__(cfg)

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
        bus = cfg.get("bus", 0)
        dev = cfg.get("dev", 0)
        f = cfg.get("f", 1000000)
        mode = cfg.get("mode", 0)
        bits = cfg.get("bits", 8)

        self._spi = spidev.SpiDev()
        self._spi.open(bus, dev)
        self._spi.max_speed_hz = f
        self._spi.mode = mode
        self._spi.bits_per_word = bits

        self._bus_id = (bus, dev)
        self.lock = _get_bus_lock(bus, dev)

    async def teardown(self):
        "shutdown"
        self._teardown()
        await super().teardown()

    def _teardown(self):
        s, self._spi = self._spi, None
        if s is not None:
            s.close()

    doc_rd = dict(
        _d="read",
        n="int:nbytes",
    )

    async def cmd_rd(self, n: int) -> bytes:
        """
        Read @n bytes from SPI.

        Args:
            n: number of bytes to read
        """
        async with self.lock:
            return bytes(await to_thread(self._spi.readbytes, n))

    doc_wr = dict(
        _d="write",
        buf="bytes:data",
        _r="int:nbytes written",
    )

    async def cmd_wr(self, buf: bytes) -> int:
        """
        Write @buf to SPI.

        Args:
            buf: data to write
        """
        async with self.lock:
            await to_thread(self._spi.writebytes, list(buf))
            return len(buf)

    doc_rw = dict(
        _d="write+read simultaneous",
        wbuf="bytes:write data",
        _r="bytes:read result",
    )

    async def cmd_rw(self, wbuf: bytes) -> bytes:
        """
        Simultaneous write and read (xfer).

        Args:
            wbuf: data to write

        Returns the same number of bytes as written.
        """
        async with self.lock:
            return bytes(await to_thread(self._spi.xfer, list(wbuf)))

    doc_wrrd = dict(
        _d="write then read (separate)",
        wbuf="bytes:write data",
        n="int:read bytes",
        _r="bytes:read result",
    )

    async def cmd_wrrd(self, wbuf: bytes, n: int) -> bytes:
        """
        Write @wbuf then read @n bytes (sequential, not simultaneous).

        This is useful for command-response protocols where you send
        a command and then read the response.

        Args:
            wbuf: data to write first
            n: number of bytes to read after
        """
        async with self.lock:
            await to_thread(self._spi.writebytes, list(wbuf))
            return bytes(await to_thread(self._spi.readbytes, n))
