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

# Per-bus cache for hardware SPI: bus_id -> [bus, lock, owner]
_bus_cache: dict[int, list] = {}


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

        # CS pin handling
        if "cs" in cfg:
            self.cs_pin = machine.Pin(cfg["cs"], machine.Pin.OUT)
            self.cs_low = cfg.get("cs_low", True)
            # Initialize CS to inactive state
            self.cs_pin.value(not self.cs_low)
        else:
            self.cs_pin = None
            self.cs_low = True

        # Store SPI config for reinit
        self._spi_cfg = {
            "baudrate": cfg.get("f", 1000000),
            "polarity": cfg.get("pol", 0),
            "phase": cfg.get("pha", 0),
        }

        sck = machine.Pin(cfg["sck"])
        mosi = machine.Pin(cfg["mosi"])
        miso = machine.Pin(cfg["miso"])

        bus_id = cfg.get("id", None)
        self._bus_id = bus_id

        if bus_id is None:
            # Software SPI - each instance is independent
            self._bus = machine.SoftSPI(sck=sck, mosi=mosi, miso=miso, **self._spi_cfg)
            self.lock = Lock()
            self._cache = None
        else:
            # Hardware SPI - shared bus with reinit on owner change
            if bus_id not in _bus_cache:
                bus = machine.SPI(bus_id, sck=sck, mosi=mosi, miso=miso, **self._spi_cfg)
                _bus_cache[bus_id] = [bus, Lock(), None]
            self._cache = _bus_cache[bus_id]
            self._bus = self._cache[0]
            self.lock = self._cache[1]

    async def teardown(self):
        "shutdown"
        self._teardown()
        await super().teardown()

    def _teardown(self):
        if self._cache is not None:
            # Hardware SPI - clear ownership on shared bus
            if self._cache[2] is self:
                self._cache[2] = None
                self._bus.deinit()
            self._bus = None
        else:
            # Software SPI - we own it, always deinit
            self._bus.deinit()
            self._bus = None

    def _ensure_config(self):
        """Reinit bus if another driver used it since we did."""
        if self._cache is not None and self._cache[2] is not self:
            self._bus.init(**self._spi_cfg)
            self._cache[2] = self

    async def _with_cs(self, func):
        """
        Execute func with CS asserted.
        """
        async with self.lock:
            self._ensure_config()
            if self.cs_pin is not None:
                self.cs_pin.value(self.cs_low)  # Assert CS (active state)
            try:
                return await func()
            finally:
                if self.cs_pin is not None:
                    self.cs_pin.value(not self.cs_low)  # Deassert CS

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
            wr: no-op byte to write while reading (default 0x00)
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
        _d="read+write simultaneous",
        _0="bytes:data buffer (read into same buffer)",
        _r="bytes:read result",
        n="int:bytes to fill (>0) / chop off the end (<0)",
        wr="int:fill byte for n>0",
    )

    async def cmd_rw(self, buf: bytes, n: int = 0, wr: int = 0) -> bytes:
        """
        Simultaneous write and read (full duplex).

        Writes buf while reading into the same buffer.

        Args:
            buf: data to write
            n: if >0, add n fill bytes to the end; if <0, chop -n bytes off
               the result before returning it
            wr: the byte to use as filler for n>0

        """

        async def _run():
            if n > 0:
                buf += bytes((wr,)) * n
            await to_thread(self._bus.write_readinto, buf, buf)
            if n < 0:
                buf = memoryview(buf)[:-n]
            return buf

        return await self._with_cs(_run)
