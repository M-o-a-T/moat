"""
Access a satellite's SPI bus.
"""

from __future__ import annotations

try:
    import machine
except ImportError:
    from moat.micro._test import machine

from moat.lib.micro import Lock, to_thread
from moat.lib.rpc import BaseCmd

# Per-bus locks to prevent concurrent access
_bus_locks: dict[int | None, Lock] = {}


def _get_bus_lock(bus_id: int | None) -> Lock:
    """Get or create a lock for the given bus ID."""
    if bus_id is None:
        return Lock()
    if bus_id not in _bus_locks:
        _bus_locks[bus_id] = Lock()
    return _bus_locks[bus_id]


class Cmd(BaseCmd):
    """
    This command implements basic access to a SPI bus.

    Parameters:

        id(int|None): None  # uses soft SPI if None
        sck(int): clock pin
        mosi(int): output / MOSI (master out, slave in)
        miso(int): input / MISO (master in, slave out)
        f(int): frequency(Hz)
        pol(bool): clock polarity (0 or 1)
        pha(bool): clock phase (0 or 1)
        cs(int): chip select pin
        cs_low(bool): chip select is active low? (default: `True`)

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
        f="int:frequency",
        cs="int:CS pin",
        cs_low="bool:CS pin is active low",
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
        if "cs" in cfg:
            self.cs_pin = machine.Pin(cfg["cs"])
        else:
            self.cs_pin = None

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
            try:
                b.deinit()
            except AttributeError:
                pass

    async def _with_cs(self, func):
        """
        Execute func with CS asserted.
        """
        async with self.lock:
            if self.cs_pin is not None:
                await self.cs_pin(not self.cs_low)  # CS active low
            try:
                return await func()
            finally:
                if self.cs_pin is not None:
                    await self.cs_pin(self.cs_low)  # CS active low

    doc_r = dict(
        _d="read",
        n="int:nbytes",
        wr="int:write byte(0)",
    )

    async def cmd_r(self, n: int, wr: int = 0) -> bytes:
        """
        Read @n bytes from SPI while writing @wr byte.

        Args:
            n: number of bytes to read
            wr: byte to write while reading (default 0x00)
        """

        async def _run():
            return await to_thread(self._bus.read, n, wr)

        return await self._with_cs(_run)

    doc_w = dict(
        _d="write",
        buf="bytes:data",
        _r="int:nbytes written",
    )

    async def cmd_w(self, buf: bytes) -> int:
        """
        Write to SPI.

        Args:
            buf: data to write
        """

        async def _run():
            await to_thread(self._bus.write, buf)
            return len(buf)

        return await self._with_cs(_run)

    doc_rw = dict(
        _d="read+write",
        _0="bytes:write data",
        n="int:read bytes",
        cs="path:CS pin",
        _r="bytes:read result",
    )

    async def cmd_rw(self, buf: bytes) -> bytes:
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
            await to_thread(self._bus.write_readinto, buf, buf)
            return buf

        return await self._with_cs(_run)
