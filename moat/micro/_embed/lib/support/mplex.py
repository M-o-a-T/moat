"""
This is a button in/out multiplexer.
"""

from __future__ import annotations

import asyncio
from machine import Pin, Timer, disable_irq, enable_irq
from micropython import const

from moat.util import merge

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT = dict(
    input=(),
    output=(),
    inv=dict(scan=False, input=False, output=False),
)

SCAN = const(0)
INPUT = const(1)
OUTPUT = const(2)


class Multiplex:
    """
    Run a pin multiplexer.

    The driver pins are a list of pin numbers at cfg.scan.
    The inputs are connected to cfg.input, while the outputs are on cfg.output.
    Inputs or outputs may be empty.
    """

    def __init__(self, cfg, timer=None):
        merge(cfg, DEFAULT, replace=False)
        self.cfg = cfg
        inv = cfg["inv"]
        self.inv = inv = [inv["scan"], inv["input"], inv["output"]]  # see constants!

        self.scan = [Pin(x, mode=Pin.OUT, value=inv[SCAN]) for x in cfg["scan"]]
        self.input = [Pin(x, mode=Pin.IN, value=inv[INPUT]) for x in cfg["input"]]
        self.output = [Pin(x, mode=Pin.OUT, value=inv[OUTPUT]) for x in cfg["output"]]

        self.this = None

        self.state = 0
        self.changed = 0
        self.work = asyncio.ThreadSafeFlag()
        self.out = 0  # output state

        if timer is None:
            timer = cfg["timer"]
            if isinstance(timer, int):
                timer = Timer(timer)
        self.timer = timer

    def __getitem__(self, btn: int) -> bool:
        "Read input pin state"
        return bool(self.state & (1 << btn))

    get_in = __getitem__

    def __setitem__(self, btn: int, value: bool) -> None:
        "Write output pin state"
        mask = 1 << btn
        self.out = (self.out & ~mask) | (mask if value else 0)

    set_out = __setitem__

    def get_out(self, btn: int) -> bool:
        "Read output pin state"
        return bool(self.out & (1 << btn))

    def changes(self) -> Iterator[tuple[int, int]]:
        """
        Iterator that yields (button, true-if-pushed) tuples.
        """
        btn = len(self.scan) * len(self.input)
        if btn == 0:
            return

        self.work.clear()
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

    def start(self):
        "Start the multiplexer"
        if self.this is not None:
            raise RuntimeError("already running")
        self.this = 0
        self.imask = self.omask = 1
        self.step()
        self.timer.init(
            mode=Timer.PERIODIC, period=self.cfg["msec"], callback=self.step, hard=False
        )

    def stop(self):
        "Stop the multiplexer, de-assert all pins"
        self.timer.deinit()
        self.this = None

        v = self.inv[OUTPUT]
        for pin in self.output:
            pin(v)

        v = self.inv[SCAN]
        for pin in self.scan:
            pin(v)

    def step(self, _timer=None):
        """Run one pass of the multiplexer"""
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
        # Could only turn off those that won't stay on
        # but that eats time.
        for pin in self.output:
            pin(vo)

        self.scan[this](vs)

        this += 1
        if this == len(self.scan):
            this = 0
            imask = omask = 1

        self.scan[this](not vs)
        # turn on new outputs
        for pin in self.output:
            if self.out & omask:
                pin(not vo)
            omask <<= 1
        self.this = this
        self.imask = imask
        self.omask = omask
