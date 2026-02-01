"""
Access a satellite's SPI bus.
"""

from __future__ import annotations

try:
    import machine
except ImportError:
    from moat.micro._test import machine

import contextlib

from moat.lib.micro import Lock, to_thread
from moat.lib.rpc import BaseCmd

# Per-bus locks to prevent concurrent access
_bus_locks: dict[int | None, Lock] = {}


def _get_bus_lock(bus_id: int | None) -> Lock:
    """Get or create a lock for the given bus ID."""
    if bus_id not in _bus_locks:
        _bus_locks[bus_id] = Lock()
    return _bus_locks[bus_id]


class Cmd(BaseCmd):
    """
    This command implements basic access to a SPI bus.

    Config::

        id: None  # use soft SPI if None
        sck: 18   # pin# of clock
        mosi: 23  # pin# of MOSI (master out, slave in)
        miso: 19  # pin# of MISO (master in, slave out)
        f: 1000000  # frequency, Hz (baudrate)
        pol: 0    # clock polarity (0 or 1)
        pha: 0    # clock phase (0 or 1)

    Device operations require a CS (chip select) pin path.
    The driver controls CS: active low before operation, high after.
    """

    _bus = None

    doc = dict(
        _c=dict(_d="SPI driver"),
        id="int|None:hardware bus ID",
        sck="int:clock pin",
        mosi="int:MOSI pin",
        miso="int:MISO pin",
        f="int:frequency/baudrate",
        pol="int:polarity(0)",
        pha="int:phase(0)",
    )

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
        sck = machine.Pin(cfg["sck"])
        mosi = machine.Pin(cfg["mosi"])
        miso = machine.Pin(cfg["miso"])
        f = cfg.get("f", 1000000)
        pol = cfg.get("pol", 0)
        pha = cfg.get("pha", 0)

        bus_id = cfg.get("id", None)
        if bus_id is None:
            cls = machine.SoftSPI
            self._bus = cls(baudrate=f, polarity=pol, phase=pha, sck=sck, mosi=mosi, miso=miso)
        else:
            self._bus = machine.SPI(
                bus_id, baudrate=f, polarity=pol, phase=pha, sck=sck, mosi=mosi, miso=miso
            )
        self._bus_id = bus_id
        self.lock = _get_bus_lock(bus_id)

    async def teardown(self):
        "shutdown"
        self._teardown()
        await super().teardown()

    def _teardown(self):
        b, self._bus = self._bus, None
        if b is not None:
            with contextlib.suppress(AttributeError):
                b.deinit()

    async def _cs_ctx(self, cs_path):
        """
        Get the CS pin handler from the path.
        Returns a pin object that can be written to.
        """
        if cs_path is None:
            return None
        return self.root.sub_at(cs_path)

    async def _with_cs(self, cs, func):
        """
        Execute func with CS asserted (low), then deassert (high).
        """
        if cs is not None:
            cs_pin = await self._cs_ctx(cs)
            await cs_pin.w(v=False)  # CS active low
        try:
            return await func()
        finally:
            if cs is not None:
                await cs_pin.w(v=True)  # CS inactive high

    doc_rd = dict(
        _d="read",
        n="int:nbytes",
        cs="path:CS pin",
        wr="int:write byte(0)",
    )

    async def cmd_rd(self, n: int, cs=None, wr: int = 0) -> bytes:
        """
        Read @n bytes from SPI while writing @wr byte.

        Args:
            n: number of bytes to read
            cs: path to chip select pin (optional)
            wr: byte to write while reading (default 0x00)
        """

        async def _run():
            return await to_thread(self._bus.read, n, wr)

        async with self.lock:
            return await self._with_cs(cs, _run)

    doc_wr = dict(
        _d="write",
        buf="bytes:data",
        cs="path:CS pin",
        _r="int:nbytes written",
    )

    async def cmd_wr(self, buf: bytes, cs=None) -> int:
        """
        Write @buf to SPI.

        Args:
            buf: data to write
            cs: path to chip select pin (optional)
        """

        async def _run():
            await to_thread(self._bus.write, buf)
            return len(buf)

        async with self.lock:
            return await self._with_cs(cs, _run)

    doc_rw = dict(
        _d="write+read simultaneous",
        wbuf="bytes:write data",
        n="int:read bytes (len(wbuf) if None)",
        cs="path:CS pin",
        _r="bytes:read result",
    )

    async def cmd_rw(self, wbuf: bytes, n: int | None = None, cs=None) -> bytes:
        """
        Simultaneous write and read.

        Args:
            wbuf: data to write
            n: number of bytes to read (defaults to len(wbuf))
            cs: path to chip select pin (optional)

        If n > len(wbuf), the write buffer is padded with zeros.
        If n < len(wbuf), only n bytes are transferred.
        """
        if n is None:
            n = len(wbuf)

        async def _run():
            # Adjust buffers to same size
            if n == len(wbuf):
                rbuf = bytearray(n)
                await to_thread(self._bus.write_readinto, wbuf, rbuf)
            elif n > len(wbuf):
                # Pad write buffer
                wb = bytearray(n)
                wb[: len(wbuf)] = wbuf
                rbuf = bytearray(n)
                await to_thread(self._bus.write_readinto, wb, rbuf)
            else:
                # Truncate to n bytes
                wb = wbuf[:n]
                rbuf = bytearray(n)
                await to_thread(self._bus.write_readinto, wb, rbuf)
            return bytes(rbuf)

        async with self.lock:
            return await self._with_cs(cs, _run)

    doc_wrrd = dict(
        _d="write then read (separate)",
        wbuf="bytes:write data",
        n="int:read bytes",
        cs="path:CS pin",
        _r="bytes:read result",
    )

    async def cmd_wrrd(self, wbuf: bytes, n: int, cs=None) -> bytes:
        """
        Write @wbuf then read @n bytes (sequential, not simultaneous).

        This is useful for command-response protocols where you send
        a command and then read the response.

        Args:
            wbuf: data to write first
            n: number of bytes to read after
            cs: path to chip select pin (optional)
        """

        async def _run():
            await to_thread(self._bus.write, wbuf)
            return await to_thread(self._bus.read, n)

        async with self.lock:
            return await self._with_cs(cs, _run)
