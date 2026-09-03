"""
Unit tests for the MPlex multiplexed-I/O part.

These tests exercise the scanning algorithm, bitmask manipulation, inversion
logic, and change-tracking of ``moat.micro.part.mplex.MPlex`` without real
hardware.  Because the part imports ``machine`` and ``micropython``
(MicroPython-only modules), we inject lightweight stubs into ``sys.modules``
before importing the part via ``importlib``.
"""
# ruff:noqa:SLF001,D102,PLC0415

from __future__ import annotations

import importlib.util
import pytest
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Stubs for MicroPython-only modules
# ---------------------------------------------------------------------------

_SENTINEL = object()


class FakePin:
    """Controllable fake of ``machine.Pin``."""

    IN = 0
    OUT = 1

    def __init__(self, pin_num, mode=0, value=0):
        self._pin_num = pin_num
        self.mode = mode
        self._value = bool(value)

    def __call__(self, value=_SENTINEL):
        if value is _SENTINEL:
            return self._value
        self._value = bool(value)

    def simulate(self, value):
        """Externally set the pin's input value (simulate a button press)."""
        self._value = bool(value)


class FakeTimer:
    """Manual-stepping fake of ``machine.Timer``."""

    PERIODIC = 1

    def __init__(self, timer_id):
        self._timer_id = timer_id
        self._callback = None
        self._initialized = False

    def init(self, mode=1, period=0, callback=None, hard=False):
        self._mode = mode
        self._period = period
        self._callback = callback
        self._hard = hard
        self._initialized = True

    def deinit(self):
        self._initialized = False
        self._callback = None

    def tick(self):
        """Fire the timer callback once (manual stepping)."""
        if self._callback:
            self._callback(self)


class FakeThreadSafeFlag:
    """Minimal stand-in for MicroPython's ``asyncio.ThreadSafeFlag``."""

    def __init__(self):
        self._set = False

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    async def wait(self):
        pass


# Track irq disable/enable calls for assertion
_irq_log: list[str] = []


def _install_stubs():
    """Install fake ``machine``, ``micropython``, and ``ThreadSafeFlag``."""
    machine_mod = types.ModuleType("machine")
    machine_mod.Pin = FakePin
    machine_mod.Timer = FakeTimer
    machine_mod.Pin.IN = 0
    machine_mod.Pin.OUT = 1
    machine_mod.Timer.PERIODIC = 1
    sys.modules["machine"] = machine_mod

    mp_mod = types.ModuleType("micropython")
    mp_mod.const = lambda x: x

    def _disable_irq():
        _irq_log.append("disable")
        return 0

    def _enable_irq(_state):
        _irq_log.append("enable")

    mp_mod.disable_irq = _disable_irq
    mp_mod.enable_irq = _enable_irq
    sys.modules["micropython"] = mp_mod

    import asyncio

    if not hasattr(asyncio, "ThreadSafeFlag"):
        asyncio.ThreadSafeFlag = FakeThreadSafeFlag


_install_stubs()

# ---------------------------------------------------------------------------
# Import the part module from its file path
# ---------------------------------------------------------------------------

_MPLEX_PATH = (
    Path(__file__).resolve().parent.parent / "moat/micro/_embed/lib/moat/micro/part/mplex.py"
)

spec = importlib.util.spec_from_file_location("_test_part_mplex", _MPLEX_PATH)
assert spec is not None
_mplex_mod = importlib.util.module_from_spec(spec)
sys.modules["_test_part_mplex"] = _mplex_mod
spec.loader.exec_module(_mplex_mod)

MPlex = _mplex_mod.MPlex
SCAN = _mplex_mod.SCAN
INPUT = _mplex_mod.INPUT
OUTPUT = _mplex_mod.OUTPUT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(scan=(0, 1), input_=None, output=(5, 6), inv=None, timer=0, msec=50):
    """Build a minimal attrdict config for MPlex."""
    from moat.util import attrdict

    if input_ is None:
        input_ = (2, 3, 4)
    if inv is None:
        inv = dict(scan=False, input=False, output=False)
    return attrdict(
        scan=list(scan),
        input=list(input_),
        output=list(output),
        inv=inv,
        timer=timer,
        msec=msec,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_basic():
    """Construct MPlex with 2 scan, 3 input, 2 output pins."""
    mpx = MPlex(_cfg())
    assert len(mpx.scan) == 2
    assert len(mpx.input) == 3
    assert len(mpx.output) == 2
    assert mpx.state == 0
    assert mpx.changed == 0
    assert mpx.out == 0
    assert mpx.this is None  # not started
    assert mpx.inv == [False, False, False]


def test_init_empty_inputs():
    """Zero input pins: construction succeeds, step/drain work without error."""
    mpx = MPlex(_cfg(input_=()))
    assert len(mpx.input) == 0
    mpx._start_scan()
    mpx.step()  # should not crash
    changes = list(mpx._drain_changes())
    assert changes == []
    mpx._stop_scan()


def test_init_empty_outputs():
    """Zero output pins: construction succeeds, step skips output driving."""
    mpx = MPlex(_cfg(output=()))
    assert len(mpx.output) == 0
    mpx._start_scan()
    mpx.step()  # should not crash
    mpx._stop_scan()


def test_start_stop():
    """_start_scan initializes scanning; _stop_scan tears it down."""
    mpx = MPlex(_cfg())
    mpx._start_scan()
    assert mpx.this is not None
    assert mpx._timer is not None
    assert mpx._timer._initialized

    mpx._stop_scan()
    assert mpx.this is None
    assert mpx._timer is None
    # all output and scan pins de-asserted to inverted-rest value
    for pin in mpx.output:
        assert pin() == mpx.inv[OUTPUT]
    for pin in mpx.scan:
        assert pin() == mpx.inv[SCAN]


def test_step_advances_scan_position():
    """With 3 scan pins, this cycles 0->1->2->0 and masks reset on wrap."""
    mpx = MPlex(_cfg(scan=(0, 1, 2)))
    mpx._start_scan()
    positions = set()
    for _ in range(6):
        positions.add(mpx.this)
        mpx.step()
    assert {0, 1, 2}.issubset(positions)
    mpx._stop_scan()


def test_step_reads_input_change():
    """Setting a fake input pin active causes state/changed to update."""
    mpx = MPlex(_cfg(scan=(0,), input_=(2,)))
    mpx._start_scan()
    mpx.state = 0
    mpx.changed = 0
    mpx.work.clear()
    mpx.input[0].simulate(True)
    mpx.step()
    assert mpx.state & 1  # bit 0 set
    assert mpx.changed & 1  # change detected
    assert mpx.work._set  # flag was set
    mpx._stop_scan()


def test_step_no_change_no_flag():
    """Input staying the same across step() does not set changed or flag."""
    mpx = MPlex(_cfg(scan=(0,), input_=(2,)))
    mpx._start_scan()
    mpx.state = 0
    mpx.changed = 0
    mpx.work.clear()
    mpx.input[0].simulate(False)
    mpx.step()
    assert mpx.changed == 0
    assert not mpx.work._set
    mpx._stop_scan()


def test_drain_changes():
    """Multiple input changes are drained as (btn, pressed) tuples."""
    mpx = MPlex(_cfg(scan=(0, 1), input_=(2, 3)))
    mpx._start_scan()
    mpx.changed = 0b0101  # bits 0 and 2 changed
    mpx.state = 0b0101  # bit 0 = pressed, bit 2 = pressed
    changes = list(mpx._drain_changes())
    buttons = sorted(c[0] for c in changes)
    pressed = [c[1] for c in changes]
    assert buttons == [0, 2]
    assert all(pressed)
    assert mpx.changed == 0  # all cleared
    mpx._stop_scan()


def test_get_in_set_out_get_out():
    """get_in reads state bitmask; set_out/get_out manipulate output bitmask."""
    mpx = MPlex(_cfg())
    mpx.state = 1 << 3  # bit 3 set
    assert mpx.get_in(3) is True
    assert mpx.get_in(0) is False

    mpx.set_out(5, True)
    assert mpx.get_out(5) is True
    assert mpx.get_out(4) is False

    mpx.set_out(5, False)
    assert mpx.get_out(5) is False


def test_inversion_flags():
    """Active-low inversion: pin reading == vi means NOT pressed."""
    mpx = MPlex(_cfg(scan=(0,), input_=(2,), inv=dict(scan=True, input=True, output=True)))
    assert mpx.inv == [True, True, True]
    mpx._start_scan()
    mpx.state = 0
    mpx.changed = 0
    mpx.work.clear()
    # With input inverted (vi=True), pin()==True means NOT pressed (val=0)
    # pin()==False means pressed (val=imask)
    mpx.input[0].simulate(False)  # False != True(vi) -> pressed
    mpx.step()
    assert mpx.state & 1  # bit 0 set (pressed)
    mpx._stop_scan()


def test_step_drives_output_pins():
    """set_out then step drives the corresponding output pin active."""
    mpx = MPlex(_cfg(scan=(0,), input_=(), output=(5,)))
    mpx._start_scan()
    mpx.set_out(0, True)
    mpx.step()
    # vo = inv[OUTPUT] = False, so active = not False = True
    assert mpx.output[0]() is True
    mpx._stop_scan()


def test_double_start_raises():
    """Calling _start_scan twice raises RuntimeError."""
    mpx = MPlex(_cfg())
    mpx._start_scan()
    with pytest.raises(RuntimeError, match="already running"):
        mpx._start_scan()
    mpx._stop_scan()


def test_stop_when_not_running():
    """_stop_scan without prior _start_scan is a harmless no-op."""
    mpx = MPlex(_cfg())
    mpx._stop_scan()  # should not raise
    assert mpx.this is None


def test_disable_enable_irq_in_drain():
    """_drain_changes calls disable_irq/enable_irq around each bit-clear."""
    _irq_log.clear()
    mpx = MPlex(_cfg(scan=(0,), input_=(2,)))
    mpx._start_scan()
    mpx.changed = 1  # one bit changed
    mpx.state = 1
    list(mpx._drain_changes())
    assert "disable" in _irq_log
    assert "enable" in _irq_log
    mpx._stop_scan()
