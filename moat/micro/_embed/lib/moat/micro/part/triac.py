"""
Triac control with phase-angle triggering.

A triac is a solid-state switch for AC loads.  Once triggered it
conducts until the next natural zero crossing of the AC supply — there
is no way to actively turn a triac off.  Power is controlled by
**phase-angle triggering**: after each zero crossing the gate is
pulsed after a delay proportional to ``(1-val)`` of the half-cycle.

This module is MicroPython-only: it uses a hardware interrupt on the
zero-crossing input pin (recording microsecond timestamps) and a
hardware ``Timer`` to fire the gate pulse at the correct phase angle.

The line frequency is measured adaptively from the zero-crossing
timestamps.  Glitches (outlier intervals) are rejected by a median
filter.
"""

from __future__ import annotations

from time import ticks_diff, ticks_us

import asyncio
from machine import Pin, Timer

from moat.util import NotGiven
from moat.lib.micro import AC_use, Event, TaskGroup
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


# Number of ZC intervals to keep for frequency estimation.
_HIST = 5


class Triac(BaseCmd):
    """
    A triac is an AC output whose power is controlled by phase-angle
    triggering.

    The value is a float in [0..1].  After each zero crossing the gate
    is pulsed after a delay of ``(1-val) * half_cycle`` microseconds.
    At ``val == 1.0`` the gate is held on continuously; at ``val == 0``
    it is never fired.  Because a triac cannot be turned off actively,
    setting the value to 0 merely stops further gate pulses — the triac
    extinguishes at the next natural zero crossing.

    A zero-crossing detector input pin is required.  Its interrupt
    records microsecond timestamps; the line frequency is estimated
    adaptively from these timestamps with glitch rejection.

    Parameters:
        pin(int): gate output pin number.
        zero(int): zero-crossing detector input pin number.
        invert(bool): invert the gate output (active-low).
        zc_edge(int): which edge to trigger on.  ``0`` = falling
            (default), ``1`` = rising, ``2`` = both.
        timer(int): hardware timer number for the gate pulse.
        pulse(int): gate pulse width in microseconds (default 100).
        cycle(int): nominal AC cycle period in milliseconds
            (default 20, i.e. 50 Hz).  Used as an initial estimate only;
            the actual frequency is measured from ZC interrupts.
    """

    doc = dict(
        _c=dict(
            _d="Triac output",
            pin="int:Gate output pin nr",
            zero="int:Zero-crossing input pin nr",
            invert="bool:Invert gate output",
            zc_edge="int:ZC edge (0=fall,1=rise,2=both)",
            timer="int:Hardware timer nr",
            pulse="int:Gate pulse width (μs,100)",
            cycle="int:Nominal AC cycle (ms,20)",
        ),
        _d="SDP:get/set value",
        _a=[
            dict(_d="get value", _r="float:power [0..1]"),
            dict(_d="set value", _0="float:power [0..1]"),
        ],
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        self._gate = Pin(cfg["pin"], Pin.OUT, value=0)
        self._invert = cfg.get("invert", False)
        edge_map = {
            0: Pin.IRQ_FALLING,
            1: Pin.IRQ_RISING,
            2: Pin.IRQ_FALLING | Pin.IRQ_RISING,
        }
        zc_edge = cfg.get("zc_edge", 0)
        self._zc_pin = Pin(
            cfg["zero"],
            Pin.IN,
        )
        self._zc_flags = edge_map.get(zc_edge, Pin.IRQ_FALLING)
        self._pulse = cfg.get("pulse", 100)
        self._nominal_cycle = cfg.get("cycle", 20)

        self.value: float = 0.0
        self.force: float | None = None

        # ZC timestamp history (microseconds).  Most-recent last.
        self._zc_hist: list[int] = []
        # Estimated half-cycle period in microseconds.
        self._half_us: int = self._nominal_cycle * 1000 // 2
        # Timer for gate pulse.
        self._timer = Timer(cfg.get("timer", 1))
        # Event to signal value changes to the main task.
        self.evt = Event()
        # Flag for ISR → task communication.
        self._flag = asyncio.ThreadSafeFlag()
        # Whether the gate is currently held on (100 % mode).
        self._held = False

    async def reload(self):
        """Reload config."""
        # Pin/timer allocation is permanent; only update tunables.
        self._pulse = self.cfg.get("pulse", 100)
        self._invert = self.cfg.get("invert", False)
        await super().reload()

    async def setup(self):  # noqa:D102
        await super().setup()
        self.tg = await AC_use(self, TaskGroup())
        # Set initial gate state.
        self._gate_write(False)
        # Enable ZC interrupt.
        self._zc_pin.irq(self._zc_isr, self._zc_flags)

    async def task(self):  # noqa:D102
        self.set_ready()
        try:
            while True:
                await self._flag.wait()
                self._flag.clear()
                self._update_timer()
        finally:
            self._zc_pin.irq(None)
            self._timer.deinit()
            self._gate_write(False)

    def _gate_write(self, on: bool) -> None:
        """Write the gate pin, respecting inversion."""
        self._gate.value(1 if on != self._invert else 0)

    def _zc_isr(self, _pin) -> None:
        """Zero-crossing interrupt handler — records timestamp."""
        now = ticks_us()
        self._zc_hist.append(now)
        if len(self._zc_hist) > _HIST:
            self._zc_hist.pop(0)
        self._estimate_freq()
        self._flag.set()

    def _estimate_freq(self) -> None:
        """
        Estimate the half-cycle period from recent ZC timestamps.

        Uses a median of the recent intervals to reject glitches.
        """
        hist = self._zc_hist
        if len(hist) < 2:
            return
        intervals = []
        for i in range(1, len(hist)):
            d = ticks_diff(hist[i], hist[i - 1])
            if d > 0:
                intervals.append(d)
        if not intervals:
            return
        intervals.sort()
        # Median.
        mid = len(intervals) // 2
        med = intervals[mid]
        # Sanity check: reject if wildly out of range (>2× or <0.5× nominal).
        nom_half = self._nominal_cycle * 1000 // 2
        if med > nom_half * 2 or med < nom_half // 2:
            return
        self._half_us = med

    def _effective(self) -> float:
        """Return the effective output value (force overrides value)."""
        if self.force is not None:
            return self.force
        return self.value

    def _update_timer(self) -> None:
        """
        Schedule the gate pulse based on the current value and
        measured half-cycle period.

        Called after each ZC interrupt (via the ThreadSafeFlag path)
        or after a value change.
        """
        val = self._effective()

        if val <= 0.0:
            # Stop firing — triac turns off at next natural ZC.
            self._timer.deinit()
            if self._held:
                self._gate_write(False)
                self._held = False
            return

        if val >= 1.0:
            # Hold the gate on continuously.
            self._timer.deinit()
            self._gate_write(True)
            self._held = True
            return

        # Phase-angle: fire after delay = (1-val) * half_cycle.
        self._held = False
        delay_us = int((1.0 - val) * self._half_us)
        if delay_us < 0:
            delay_us = 0

        self._timer.init(
            mode=Timer.ONE_SHOT,
            period=delay_us,
            callback=self._fire_gate,
        )

    def _fire_gate(self, _timer) -> None:
        """Timer callback: pulse the gate."""
        self._gate_write(True)
        # Schedule turn-off after pulse width.
        # On MicroPython we use a second one-shot timer.
        self._timer.init(
            mode=Timer.ONE_SHOT,
            period=self._pulse,
            callback=self._off_gate,
        )

    def _off_gate(self, _timer) -> None:
        """Timer callback: turn off the gate pulse."""
        if not self._held:
            self._gate_write(False)

    doc_w = dict(_d="set value", _0="float:new power [0..1]", f="float|None:force?")

    async def cmd_w(self, v: float = 0.0, f=NotGiven) -> None:
        """
        Change triac power.

        The power is set to @f ("force"), or @v ("value") if @f is None,
        or the current value if @v is None too.

        If you don't pass a @force argument in, the forcing state of the
        triac is not changed.
        """
        if f is NotGiven:
            f = self.force
        else:
            self.force = f

        if v is not None:
            self.value = v

        self._update_timer()

    doc_r = dict(
        _d="get state",
        _r=dict(
            v="float:set value",
            f="float:forced value",
            p="bool:gate state",
            h="int:half-cycle (μs)",
        ),
    )

    async def cmd_r(self) -> Mapping:
        """
        Returns the current state, as a mapping.

        v: currently set value
        f: currently forced value
        p: actual gate pin state
        h: measured half-cycle period in microseconds
        """
        return dict(
            v=self.value,
            f=self.force,
            p=bool(self._gate.value()),
            h=self._half_us,
        )

    async def cmd(self, v: float | None = None) -> float | None:
        """Simple Data Protocol."""
        if v is None:
            return self.value
        self.value = v
        self._update_timer()
        return None
