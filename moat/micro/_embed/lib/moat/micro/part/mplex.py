"""Pin multiplexer.

This module implements a time-multiplexed I/O expander.  A set of "scan"
pins select rows/columns in sequence; "input" pins read the selected
row, and "output" pins drive the selected column.

The scanning is driven by a hardware timer.  Input changes are collected
as ``(button, pressed)`` pairs and exposed via an async iterator and an
RPC stream.

This module is MicroPython-only: it uses ``machine.Pin``,
``machine.Timer``, and ``micropython.disable_irq`` / ``enable_irq``.
"""

from __future__ import annotations

import asyncio
from machine import Pin, Timer
from micropython import const, disable_irq, enable_irq

from moat.util import merge
from moat.lib.micro import Event, L, TaskGroup, idle
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg

    from collections.abc import Iterator

SCAN = const(0)
INPUT = const(1)
OUTPUT = const(2)

DEFAULT = dict(
    input=(),
    output=(),
    inv=dict(scan=False, input=False, output=False),
)


class MPlex(BaseCmd):
    """Time-multiplexed pin expander.

    A set of scan pins selects rows in rotation.  Input pins read the
    currently-selected row; output pins drive it.

    Parameters
    ----------
    scan : list[int]
        Pin numbers for the scan/row-select lines.
    input : list[int]
        Pin numbers for input columns.  May be empty.
    output : list[int]
        Pin numbers for output columns.  May be empty.
    inv : dict
        Inversion flags::

            scan(bool): scan pins are active-low
            input(bool): input pins are active-low
            output(bool): output pins are active-low
    msec : int
        Scan interval in milliseconds.
    timer : int
        Hardware timer ID to use for scanning.
    """

    doc = dict(
        _c=dict(
            _d="Pin multiplexer",
            scan="list:int:scan pin numbers",
            input="list:int:input pin numbers",
            output="list:int:output pin numbers",
            inv=dict(
                scan="bool:scan pins active-low?",
                input="bool:inputs active-low?",
                output="bool:outputs active-low?",
            ),
            msec="int:scan interval (ms)",
            timer="int:timer ID",
        ),
        _d="SDP:get/set output bit",
        _a=[
            dict(_d="read output bit", _0="int:bit#", _r="bool:state"),
            dict(_d="write output bit", _0="int:bit#", _1="bool:state"),
        ],
    )

    def __init__(self, cfg: dict) -> None:
        super().__init__(cfg)
        merge(cfg, DEFAULT, replace=False)
        inv = cfg["inv"]
        inv = self.inv = [inv["scan"], inv["input"], inv["output"]]

        self.scan: list[Pin] = [Pin(x, mode=Pin.OUT, value=inv[SCAN]) for x in cfg["scan"]]
        self.input: list[Pin] = [Pin(x, mode=Pin.IN, value=inv[INPUT]) for x in cfg["input"]]
        self.output: list[Pin] = [Pin(x, mode=Pin.OUT, value=inv[OUTPUT]) for x in cfg["output"]]

        self.state: int = 0
        self.changed: int = 0
        self.work: asyncio.ThreadSafeFlag = asyncio.ThreadSafeFlag()
        self.out: int = 0  # output bitmask
        self.evt: Event = Event()

        self.this: int | None = None  # current scan position; None = stopped
        self.imask: int = 0
        self.omask: int = 0
        self._timer_cfg: int = cfg["timer"]
        self._msec: int = cfg["msec"]
        self._timer: Timer | None = None

    async def setup(self) -> None:  # noqa:D102
        await super().setup()
        self._start_scan()

    async def task(self) -> None:  # noqa:D102
        async with TaskGroup() as self.__tg:
            self.__tg.start_soon(self._reader)
            if L:
                self.set_ready()
            await idle()

    async def teardown(self) -> None:  # noqa:D102
        self._stop_scan()
        await super().teardown()

    def _start_scan(self) -> None:
        """Start the hardware timer and scanning."""
        if self.this is not None:
            raise RuntimeError("already running")
        self.this = 0
        self.imask = self.omask = 1
        self.step()
        self._timer = Timer(self._timer_cfg)
        self._timer.init(mode=Timer.PERIODIC, period=self._msec, callback=self.step, hard=False)

    def _stop_scan(self) -> None:
        """Stop scanning, de-assert all pins."""
        if self.this is None:
            return
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        self.this = None

        v = self.inv[OUTPUT]
        for pin in self.output:
            pin(v)
        v = self.inv[SCAN]
        for pin in self.scan:
            pin(v)

    def step(self, _timer: Timer | None = None) -> None:
        """Run one scan pass."""
        vs = self.inv[SCAN]
        vi = self.inv[INPUT]
        vo = self.inv[OUTPUT]

        this = self.this
        imask = self.imask
        omask = self.omask

        # Read inputs.
        for pin in self.input:
            val = 0 if pin() == vi else imask
            if (self.state & imask) != val:
                self.state = (self.state & ~imask) | val
                self.changed |= imask
                self.work.set()
            imask <<= 1

        # Turn off old outputs.
        for pin in self.output:
            pin(vo)

        self.scan[this](vs)
        this += 1
        if this == len(self.scan):
            this = 0
            imask = omask = 1

        self.scan[this](not vs)
        # Turn on new outputs.
        for pin in self.output:
            if self.out & omask:
                pin(not vo)
            omask <<= 1

        self.this = this
        self.imask = imask
        self.omask = omask

    async def _reader(self) -> None:
        """Forward hardware-flag changes to the async Event."""
        while True:
            await self.work.wait()
            self.work.clear()
            self.evt.set()
            self.evt = Event()

    def _drain_changes(self) -> Iterator[tuple[int, int]]:
        """Yield (button, pressed) tuples for all pending changes."""
        btn = len(self.scan) * len(self.input)
        if btn == 0:
            return

        btn -= 1
        mask = 1 << btn
        while btn >= 0:
            if self.changed & mask:
                i_ = disable_irq()
                self.changed &= ~mask
                enable_irq(i_)
                yield btn, bool(self.state & mask)
            mask >>= 1
            btn -= 1

    def get_in(self, btn: int) -> bool:
        """Read input pin state by button index."""
        return bool(self.state & (1 << btn))

    def set_out(self, btn: int, value: bool) -> None:
        """Set output pin state by button index."""
        mask = 1 << btn
        self.out = (self.out & ~mask) | (mask if value else 0)

    def get_out(self, btn: int) -> bool:
        """Read output pin state by button index."""
        return bool(self.out & (1 << btn))

    doc_r = dict(
        _d="read input",
        _0="int:button#",
        _r="bool:state",
    )

    async def cmd_r(self, btn: int) -> bool:
        """Read the state of input button @btn."""
        return self.get_in(btn)

    doc_w = dict(
        _d="set output",
        _0="int:button#",
        _1="bool:state",
    )

    async def cmd_w(self, btn: int, val: bool) -> None:
        """Set the state of output button @btn to @val."""
        self.set_out(btn, val)

    doc_o = dict(
        _d="read output state",
        _0="int:button#",
        _r="bool:state",
    )

    async def cmd_o(self, btn: int) -> bool:
        """Read the current output state of button @btn."""
        return self.get_out(btn)

    doc_i = dict(
        _d="stream input changes",
        _s=True,
    )

    async def stream_i(self, msg: Msg) -> None:
        """Stream input-change events.

        Each message is a tuple ``(button, pressed)``.
        """
        async with msg.stream_out() as m:
            while True:
                await self.evt.wait()
                for btn, val in self._drain_changes():
                    await m.send(btn, val)
