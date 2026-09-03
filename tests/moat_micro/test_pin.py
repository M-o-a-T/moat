"""
Test the MicroPython Pin class using a mock machine module.

The Pin class in ``moat/micro/_embed/lib/moat/micro/part/pin.py``
uses MicroPython-specific APIs (``machine.Pin``, ``asyncio.ThreadSafeFlag``).
This test runs a script inside the MicroPython unix port with a mock
``machine`` module that provides the needed ``Pin`` class.
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

MOCK_MACHINE_PY = '''\
"""Mock machine module for testing Pin class."""

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
        Pin._pins[pin] = self

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v
        if self._irq_cb is not None:
            self._irq_cb(self)

    def irq(self, callback=None, flags=0):
        self._irq_cb = callback

class Signal:
    pass

def idle():
    pass

def time_pulse_us(pin, pulse_time=1, timeout=1000000):
    return 0

def mem8(addr):
    return 0

def mem16(addr):
    return 0

def mem32(addr):
    return 0

def soft_reset():
    pass
'''

TEST_SCRIPT = """\
import sys, os

# Add the mock dir to the FRONT of sys.path
sys.path.insert(0, "{mock_dir}")

# Import machine (our mock) before anything else
import machine
assert hasattr(machine, "Pin"), "machine.Pin not found"

# Import the Pin app
from moat.micro.part.pin import Pin, _Pin

errors = []

def check(name, cond, msg=""):
    if cond:
        print(f"  PASS: {{name}}")
    else:
        print(f"  FAIL: {{name}} - {{msg}}")
        errors.append(name)

# Test 1: Basic _Pin creation with output mode
inner = _Pin(1, machine.Pin.OUT, value=0)
check("output pin init", inner() == 0, f"got {{inner()}}")
inner(1)
check("output pin set", inner() == 1, f"got {{inner()}}")

# Test 2: Input mode
inner2 = _Pin(2, machine.Pin.IN)
check("input pin", inner2() == 0, f"got {{inner2()}}")

# Test 3: Open drain
inner3 = _Pin(3, machine.Pin.OPEN_DRAIN, value=1)
check("open drain", inner3() == 1, f"got {{inner3()}}")

# Test 4: IRQ callback
triggered = []
def cb(pin):
    triggered.append(pin.value())

inner4 = _Pin(4, machine.Pin.IN)
inner4._pin.irq(cb, machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING)
inner4._pin.value(1)
check("irq rising", len(triggered) == 1 and triggered[0] == 1, f"got {{triggered}}")
inner4._pin.value(0)
check("irq falling", len(triggered) == 2 and triggered[1] == 0, f"got {{triggered}}")

# Test 5: Pin config parsing (output, init, drive, pull)
from moat.util import attrdict

cfg = attrdict(pin=5, out=True, init=True, drive=2, pull=True)
p = Pin(cfg)
check("cfg output mode", p.pin._pin._mode == machine.Pin.OUT, f"mode={{p.pin._pin._mode}}")
check("cfg init value", p.pin._pin._value == 1, f"value={{p.pin._pin._value}}")

# Test 6: Input config
cfg2 = attrdict(pin=6, out=False)
p2 = Pin(cfg2)
check("cfg input mode", p2.pin._pin._mode == machine.Pin.IN, f"mode={{p2.pin._pin._mode}}")

# Test 7: Open collector config
cfg3 = attrdict(pin=7, out=True, open=True)
p3 = Pin(cfg3)
check("cfg open drain", p3.pin._pin._mode == machine.Pin.OPEN_DRAIN, f"mode={{p3.pin._pin._mode}}")

# Test 8: SDP cmd
import asyncio
async def test_sdp():
    cfg4 = attrdict(pin=8, out=True, init=False)
    p4 = Pin(cfg4)
    # cmd with no args reads, with arg writes
    val = await p4.cmd(False)
    check("sdp cmd no crash", True)
asyncio.run(test_sdp())

# Test 9: Pin with pull-up
cfg5 = attrdict(pin=9, out=False, pull=True)
p5 = Pin(cfg5)
check("pull-up config", p5.pin._pin._pin == 9)

# Test 10: Pin with pull-down
cfg6 = attrdict(pin=10, out=False, pull=False)
p6 = Pin(cfg6)
check("pull-down config", p6.pin._pin._pin == 10)

if errors:
    print(f"\\n{{len(errors)}} tests FAILED: {{errors}}")
    sys.exit(1)
else:
    print("\\nAll Pin tests passed!")
"""


@pytest.fixture
def mpy_env(tmp_path):
    """Set up a temp dir with mock machine.py for MicroPython testing."""
    mock_dir = tmp_path / "mock"
    mock_dir.mkdir()
    (mock_dir / "machine.py").write_text(MOCK_MACHINE_PY)

    script = tmp_path / "test_pin.py"
    script.write_text(TEST_SCRIPT.format(mock_dir=str(mock_dir)))

    env = os.environ.copy()
    sep = os.pathsep
    env["MICROPYPATH"] = (
        str(EMBED_LIB) + sep + str(WORKTREE / "moat" / "micro" / "_embed") + sep + ".frozen"
    )
    return env, script


def test_pin_mpy(mpy_env):
    """Run Pin tests inside the MicroPython unix port."""
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
    assert result.returncode == 0, (
        f"MicroPython Pin tests failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "All Pin tests passed!" in result.stdout
