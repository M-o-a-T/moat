"""
Test the triac implementation.

The triac part is MicroPython-only (uses machine.Pin interrupts and
machine.Timer).  Tests run on the MicroPython unix port with a mock
machine module.
"""

from __future__ import annotations

import os
import pytest
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parents[1]
MPY = WORKTREE / "build" / "mpy-unix" / "micropython"
EMBED_LIB = WORKTREE / "moat" / "micro" / "_embed" / "lib"

# Mock machine module with Pin, Timer, and IRQ support.
MOCK_MACHINE = '''
"""Mock machine module for testing."""

_ticks = [0]

class Pin:
    IN = 0
    OUT = 1
    OPEN_DRAIN = 2
    PULL_UP = 1
    PULL_DOWN = 2
    IRQ_FALLING = 1
    IRQ_RISING = 2
    DRIVE_0 = 0
    DRIVE_1 = 1
    DRIVE_2 = 2
    DRIVE_3 = 3

    _pins = {}

    def __init__(self, pin, mode=0, *args, **kw):
        self._pin = pin
        self._mode = mode
        self._value = kw.get("value", 0)
        self._irq_cb = None
        self._irq_flags = 0
        Pin._pins[pin] = self

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v

    def irq(self, callback=None, flags=0):
        if callback is None:
            self._irq_cb = None
        else:
            self._irq_cb = callback
            self._irq_flags = flags

    def _trigger(self):
        """Simulate an interrupt."""
        if self._irq_cb is not None:
            self._irq_cb(self)


class Timer:
    ONE_SHOT = 0
    PERIODIC = 1

    _timers = {}

    def __init__(self, id=-1, *args, **kw):
        self._id = id
        self._cb = None
        self._period = 0
        self._mode = 0
        self._active = False
        Timer._timers[id] = self

    def init(self, mode=0, period=0, callback=None):
        self._mode = mode
        self._period = period
        self._cb = callback
        self._active = True

    def deinit(self):
        self._active = False
        self._cb = None

    def _fire(self):
        """Simulate timer expiry."""
        if self._active and self._cb is not None:
            self._cb(self)
            if self._mode == 0:
                self._active = False


def disable_irq():
    pass


def enable_irq(state):
    pass


def time_pulse_us(*a, **kw):
    return 0


def mem8(addr):
    return 0


def mem16(addr):
    return 0


def mem32(addr):
    return 0


def soft_reset():
    pass


def ticks_us():
    return _ticks[0]


def ticks_diff(a, b):
    return a - b


def _advance(us):
    _ticks[0] += us
'''

# Test script that runs inside MicroPython unix port.
TEST_SCRIPT = """
import sys
sys.path.insert(0, "{mock_dir}")

import machine
from machine import Pin, Timer

from moat.util import attrdict
from moat.micro.part.triac import Triac

errors = []

def check(cond, msg):
    if not cond:
        errors.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:", msg)


# Test 1: Basic instantiation
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    check(True, "instantiation")
except Exception as e:
    check(False, f"instantiation: {{e}}")


# Test 2: Setup and initial state
try:
    import asyncio

    async def test_setup():
        cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
        t = Triac(cfg)
        # Manually call setup bits we need
        t._gate = Pin(1, Pin.OUT, value=0)
        t._zc_pin = Pin(2, Pin.IN)
        t._timer = Timer(0)
        t._gate_write(False)
        check(t._gate.value() == 0, "initial gate off")

    asyncio.run(test_setup())
except Exception as e:
    check(False, f"setup: {{e}}")


# Test 3: Value set/get
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    t.value = 0.5
    check(t.value == 0.5, "value set/get")
    check(t._effective() == 0.5, "effective value")
except Exception as e:
    check(False, f"value: {{e}}")


# Test 4: Force override
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    t.value = 0.3
    t.force = 0.8
    check(t._effective() == 0.8, "force overrides value")
    t.force = None
    check(t._effective() == 0.3, "force removed")
except Exception as e:
    check(False, f"force: {{e}}")


# Test 5: Frequency estimation
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    # Simulate ZC timestamps: 10ms apart (100Hz = 50Hz half-cycles)
    base = 1000000
    for i in range(5):
        t._zc_hist.append(base + i * 10000)
    t._estimate_freq()
    check(t._half_us == 10000, f"freq est: {{t._half_us}}")
except Exception as e:
    check(False, f"freq: {{e}}")


# Test 6: Glitch rejection
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    # Normal intervals with one outlier
    base = 1000000
    intervals = [10000, 10000, 50000, 10000, 10000]  # 50000 is a glitch
    ts = base
    t._zc_hist = []
    for iv in intervals:
        ts += iv
        t._zc_hist.append(ts)
    t._estimate_freq()
    # Median of [10000, 10000, 10000, 10000, 50000] is 10000
    check(t._half_us == 10000, f"glitch rejection: {{t._half_us}}")
except Exception as e:
    check(False, f"glitch: {{e}}")


# Test 7: 100% holds gate on
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    t._gate = Pin(1, Pin.OUT, value=0)
    t._timer = Timer(0)
    t._held = False
    t.value = 1.0
    t._update_timer()
    check(t._gate.value() == 1, "100%% gate on")
    check(t._held == True, "100%% held flag")
except Exception as e:
    check(False, f"100%%: {{e}}")


# Test 8: 0% turns gate off
try:
    cfg = attrdict(pin=1, zero=2, timer=0, cycle=20, pulse=100)
    t = Triac(cfg)
    t._gate = Pin(1, Pin.OUT, value=1)
    t._timer = Timer(0)
    t._held = True
    t.value = 0.0
    t._update_timer()
    check(t._gate.value() == 0, "0%% gate off")
    check(t._held == False, "0%% held flag")
except Exception as e:
    check(False, f"0%%: {{e}}")


if errors:
    print(f"\\n{{len(errors)}} test(s) failed")
    sys.exit(1)
else:
    print("\\nAll 8 tests passed!")
    sys.exit(0)
"""


@pytest.fixture
def mpy_env(tmp_path):
    """Set up mock machine module and test script for MicroPython."""
    mock_dir = tmp_path / "mock"
    mock_dir.mkdir()
    (mock_dir / "machine.py").write_text(MOCK_MACHINE)

    script = tmp_path / "test_triac_mpy.py"
    script.write_text(TEST_SCRIPT.format(mock_dir=str(mock_dir)))

    env = os.environ.copy()
    env["MICROPYPATH"] = f"{EMBED_LIB}{os.pathsep}.frozen"
    return env, script


def test_triac_mpy(mpy_env):
    """Run triac tests on MicroPython unix port."""
    if not MPY.exists():
        pytest.skip("MicroPython unix port not built")

    env, script = mpy_env
    result = subprocess.run(
        [str(MPY), str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(WORKTREE),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\\n{result.stdout}\\nstderr:\\n{result.stderr}"
    assert "All 8 tests passed!" in result.stdout
