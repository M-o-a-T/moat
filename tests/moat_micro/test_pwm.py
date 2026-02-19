"""
Test the PWM implementation: end-to-end cycling tests and resync logic.
"""
# ruff:noqa:SLF001

from __future__ import annotations

import anyio
import pytest
from unittest.mock import patch

import moat.micro.part.pwm as pwm_module
from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.micro._test import mpy_stack
from moat.micro.part.pwm import PWM, _Send


class FPWM(PWM):
    "Monkeyhacked PWM class"

    def __init__(
        self,
        min,  # noqa:A002
        max,  # noqa:A002
        base,
        sync_low=None,
        sync_high=None,
        sync_path=None,
        sync_invert=False,
    ):
        self.__xstate = None
        self.min = min
        self.max = max
        self.base = base
        self.sync_low = sync_low or {}
        self.sync_high = sync_high or {}
        self.sync_path = sync_path
        self.sync_invert = sync_invert
        self.value = 0
        self.force = None
        self.t_on = 0
        self.t_off = 0
        self.is_on = False
        self.t_last = 0
        self.__t = 0
        self.evt = anyio.Event()
        self.ps = _Send(self._ps)
        self._out_mode = None
        self._sync_active = None
        self._sync_left = None
        self._sync_suspended = False
        self._sync_next_check = 0
        self._sync_check_ms = None
        self._last_measure = 0

    async def setup(self):
        "duh"
        pass

    async def run(self):
        "duh"
        pass

    async def _ps(self, state: bool) -> None:
        "fake push-an-update"
        assert self.__xstate is None
        self.__xstate = state

    async def step(self, time_d, delay, state=None):
        "Go time_d ticks forward. Expect a state change @state and a delay @d."
        self.__t += time_d
        self.__xstate = None
        dly = await self._measure(self.__t)
        assert dly == delay
        assert self.__xstate is state

    def set_time(self, t):
        "Set the internal time (for resync testing)"
        self.__t = t

    def get_time(self):
        "Get the internal time"
        return self.__t


@pytest.mark.anyio
async def test_basic():
    "Basic PWM test"
    p = FPWM(1, 10, 100)
    p.set_times(10)
    await p.step(1, 8, None)
    await p.step(8, 1, True)
    await p.step(1, 9, False)
    await p.step(1, 8, None)
    await p.step(7, 1, None)
    await p.step(1, 1, True)
    await p.step(1, 9, False)


@pytest.mark.anyio
async def test_basic_on():
    "Basic PWM test with a lot"
    p = FPWM(1, 10, 100)
    p.set_times(90)
    await p.step(1, 9, True)
    await p.step(1, 8, None)
    await p.step(7, 1, None)
    await p.step(1, 1, False)
    await p.step(1, 9, True)


@pytest.mark.anyio
async def test_onoff():
    "on/off test"
    p = FPWM(3, 10, 100)
    p.set_times(99)
    await p.step(2, 1, None)
    await p.step(1, None, True)
    p.set_times(1)
    await p.step(2, 1, None)
    await p.step(1, None, False)
    p.set_times(50)
    await p.step(1, 2, None)
    await p.step(2, 3, True)
    await p.step(1, 2, None)
    await p.step(2, 3, False)


@pytest.mark.anyio
async def test_resync_cancelled_by_threshold():
    "Resync ends when the value drops below the low threshold."
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(
            1,
            10,
            100,
            sync_low={"threshold": 10, "input": 50, "t_sync": 0.05},
        )

        p.set_times(5)
        p.set_times(20)
        assert p._sync_active == "low"

        p.set_times(5)
        assert p._sync_active is None
        assert p._out_mode == "low"
        assert p.t_on == 0


@pytest.mark.anyio
async def test_resync_no_input():
    "No resync occurs when the low input clamp is unset."
    p = FPWM(1, 10, 100, sync_low={"threshold": 10})

    p.set_times(5)
    p.set_times(20)
    assert p._sync_active is None
    assert p._out_mode is None
    assert p.t_off == 4


# ---------------------------------------------------------------------------
# End-to-end tests using mpy_stack + _fake.Pin
# ---------------------------------------------------------------------------
# Config: min=50 ms, max=500 ms, base=100
#   val=50  → t_on=50 ms, t_off=50 ms
#   val=25  → t_on=50 ms, t_off=150 ms
#   val=0   → t_on=0  (always off; settles to "wait for event")
#   val=100 → t_off=0 (always on after min=50 ms)
#
# Anchor pattern for always-off→X transitions:
#   After w.w(0)+sleep(≥200 ms), t_last is old enough that switching to
#   any target t_off ≤ 150 ms fires the wakeup event immediately.

E2E_CFG = """
app: dir
w:
  app: part.PWM
  pin: !P p
  min: 50
  max: 500
  base: 100
p:
  app: _fake.Pin
  pin: X
"""


@pytest.mark.anyio
async def test_e2e_half(tmp_path):
    "50 % duty cycle: pin alternates every 50 ms"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Anchor in a known-off state so t_last is fresh and td > t_off=50 ms.
        await w.w(0)
        await sleep_ms(70)
        assert False is await p()

        # val=50 → t_on=t_off=50 ms.  td≈70 ms ≥ t_off → event fires at once.
        await w.w(50)
        await sleep_ms(20)  # let the scheduler switch the pin on
        assert True is await p()

        await sleep_ms(60)  # 80 ms after w.w(50): past t_on=50 ms → off
        assert False is await p()

        await sleep_ms(60)  # 140 ms after w.w(50): past t_off=50 ms → on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_always_off(tmp_path):
    "val=0 keeps the pin off permanently"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        await w.w(0)
        await sleep_ms(70)
        assert False is await p()
        await sleep_ms(100)
        assert False is await p()


@pytest.mark.anyio
async def test_e2e_always_on(tmp_path):
    "val=100 turns the pin on after min=50 ms and keeps it on"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        await w.w(100)
        # The min timer has not yet elapsed; the wakeup event was set by
        # _apply_value (t_off=0 → td≥0 always), but _measure still sees
        # td < min and returns dly=50 ms rather than switching on.
        assert False is await p()

        await sleep_ms(70)  # past min=50 ms → pin on
        assert True is await p()

        await sleep_ms(100)  # stays on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_asymmetric(tmp_path):
    "val=25 → t_on=50 ms, t_off=150 ms"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Anchor: let always-off run for 200 ms so that t_last is old enough
        # that td > t_off=150 ms when we switch to val=25.
        await w.w(0)
        await sleep_ms(200)
        assert False is await p()

        # td≈200 ms ≥ t_off=150 ms → wakeup event fires immediately.
        await w.w(25)
        await sleep_ms(20)  # let the scheduler switch the pin on
        assert True is await p()

        await sleep_ms(60)  # 80 ms after w.w(25): past t_on=50 ms → off
        assert False is await p()

        await sleep_ms(160)  # 240 ms after w.w(25): past t_off=150 ms → on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_read(tmp_path):
    "cmd_r returns the current effective value; force overrides the normal value"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))

        await w.w(42)
        assert await w.r() == 42

        # Force a different value; cmd_r must reflect it.
        await w.w(77, f=True)
        assert await w.r() == 77

        # Clear the force; cmd_r reverts to the underlying value.
        await w.w(None, f=True)
        assert await w.r() == 42


@pytest.mark.anyio
async def test_e2e_state(tmp_path):
    "cmd_s returns a well-formed state dict with correct on/off times"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))

        await w.w(50)
        s = await w.s()
        assert s["val"] == 50
        assert s["on"] == 50
        assert s["off"] == 50
        assert isinstance(s["p"], bool)


@pytest.mark.anyio
async def test_e2e_value_change(tmp_path):
    "switching from always-on to always-off turns the pin off after min ms"
    async with mpy_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        await w.w(100)  # always-on
        await sleep_ms(70)  # past min=50 ms → pin on
        assert True is await p()

        # Switch to always-off.  The pin has been on for ~20 ms; the min
        # timer needs ~30 ms more before the pin is allowed to go low.
        await w.w(0)
        await sleep_ms(10)  # still in the remaining min window
        assert True is await p()
        await sleep_ms(60)  # well past the remaining min window
        assert False is await p()


# ---------------------------------------------------------------------------
# Resync end-to-end tests
# ---------------------------------------------------------------------------
# State transitions triggered by set_times are synchronous, so cmd_s checks
# immediately after w.w() reliably observe them without any sleep.
#
# t_sync is intentionally omitted from most configs.  Without it, resync ends
# only when the value crosses the input clamp level — a deterministic,
# timing-independent condition.  This avoids the problem that the first
# _update_sync call after resync starts may have a large measure_td (equal to
# however long the PWM was sleeping in always-off mode), which would otherwise
# consume the entire t_sync budget at once.

E2E_SYNC_LOW_CFG = """
app: dir
w:
  app: part.PWM
  pin: !P p
  min: 50
  max: 500
  base: 100
  sync_low:
    threshold: 20
    input: 50
p:
  app: _fake.Pin
  pin: X
"""

E2E_SYNC_HIGH_CFG = """
app: dir
w:
  app: part.PWM
  pin: !P p
  min: 50
  max: 500
  base: 100
  sync_high:
    threshold: 80
    input: 50
p:
  app: _fake.Pin
  pin: X
"""

# t_sync=2.0 s is large enough that the initial stale measure_td (at most a
# few hundred ms) does not expire the timer before the test finishes.
E2E_SYNC_SUSP_CFG = """
app: dir
w:
  app: part.PWM
  pin: !P p
  min: 50
  max: 500
  base: 100
  sync_low:
    threshold: 20
    input: 50
    t_sync: 2.0
    t_check: 0.05
    bound: 0.5
  sync_path: !P sp
sp:
  app: _fake.Pin
  pin: SP
p:
  app: _fake.Pin
  pin: X
"""


E2E_RESYNC_TIMER_CFG = """
app: dir
w:
  app: part.PWM
  pin: !P p
  min: 50
  max: 500
  base: 100
  sync_high:
    threshold: 80
    input: 10
    t_sync: 0.15
p:
  app: _fake.Pin
  pin: X
"""


@pytest.mark.anyio
async def test_e2e_resync_timer_expires_within_period(tmp_path):
    """t_sync must expire even when it is shorter than the clamped PWM period.

    sync_high with input=10 forces effective val=min(25,10)=10 during resync,
    giving t_on=50 ms and t_off=450 ms.  t_sync=150 ms is much shorter than
    t_off, so with the old _measure-based countdown the resync would persist
    well past 150 ms.  The separate resync task must fire independently.
    """
    async with mpy_stack(tmp_path, E2E_RESYNC_TIMER_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # val=90 → always on; sleep long enough that the pin has been on for
        # > t_on=50 ms when val=25 is set, so _apply_value fires the event at once.
        await w.w(90)
        await sleep_ms(120)  # pin on and td ≈ 70 ms >> t_on=50 ms
        assert await p() is True

        # val=25 → resync: effective=min(25, input=10)=10 → t_on=50 ms, t_off=450 ms.
        # td >> t_on → event fires immediately; pin switches off on first _measure.
        # Without a separate task the _measure-based countdown only runs at pin
        # transitions; t_sync=150 ms would not expire until t_off=450 ms passes.
        await w.w(25)
        await sleep_ms(20)  # one scheduler pass → pin off
        assert await p() is False

        # At 200 ms from w.w(25): t_sync=150 ms has expired.
        # _apply_value(25) → t_off=50 ms; td ≈ 180 ms >> t_off → pin turns on.
        await sleep_ms(180)
        assert await p() is True  # FAILS without the separate resync task


@pytest.mark.anyio
async def test_e2e_resync_low(tmp_path):
    "sync_low: below threshold → always off; crossing above → clamped cycling then normal"
    async with mpy_stack(tmp_path, E2E_SYNC_LOW_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Below threshold=20 → always off.
        await w.w(10)
        await sleep_ms(100)
        assert False is await p()
        assert (await w.s())["out_mode"] == "low"

        # Cross above threshold: resync starts, clamps effective val to
        # max(30, input=50)=50 → t_on=t_off=50 ms.
        # td≈100 ms >> t_off=50 ms → wakeup event fires immediately.
        await w.w(30)
        assert (await w.s())["resync"]["mode"] == "low"
        await sleep_ms(20)  # let the scheduler switch the pin on
        assert True is await p()

        # Raise val above input=50 → resync ends immediately (no t_sync timer).
        await w.w(60)
        assert "resync" not in await w.s()


@pytest.mark.anyio
async def test_e2e_resync_high(tmp_path):
    "sync_high: above threshold → always on; crossing below → clamped cycling then normal"
    async with mpy_stack(tmp_path, E2E_SYNC_HIGH_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Above threshold=80 → always on (after min=50 ms).
        await w.w(90)
        await sleep_ms(70)
        assert True is await p()
        assert (await w.s())["out_mode"] == "high"

        # Cross below threshold: resync starts, clamps effective val to
        # min(70, input=50)=50 → t_on=t_off=50 ms.
        await w.w(70)
        assert (await w.s())["resync"]["mode"] == "high"

        # Drop val below input=50 → resync ends immediately.
        await w.w(40)
        assert "resync" not in await w.s()


@pytest.mark.anyio
async def test_e2e_resync_cancelled(tmp_path):
    "resync is cancelled immediately when the value drops back below the low threshold"
    async with mpy_stack(tmp_path, E2E_SYNC_LOW_CFG) as d:
        w = d.sub_at(P("w"))

        await w.w(10)
        await sleep_ms(100)

        await w.w(30)  # start resync
        assert (await w.s())["resync"]["mode"] == "low"

        await w.w(5)  # back below threshold → resync cancelled, out_mode restored
        s = await w.s()
        assert "resync" not in s
        assert s["out_mode"] == "low"


@pytest.mark.anyio
async def test_e2e_resync_suspended(tmp_path):
    "sync_path reading above bound suspends the resync clamp; below bound resumes it"
    async with mpy_stack(tmp_path, E2E_SYNC_SUSP_CFG) as d:
        w = d.sub_at(P("w"))
        sp = d.sub_at(P("sp"))

        await w.w(10)
        await sleep_ms(100)

        await w.w(30)  # start resync
        assert (await w.s())["resync"]["mode"] == "low"

        # sp=True → value=1 > bound=0.5 → resync suspended after next t_check.
        await sp(True)
        await sleep_ms(60)  # one t_check interval (50 ms) passes
        assert (await w.s())["resync"]["suspended"] is True

        # sp=False → value=0 < bound=0.5 → resync resumes after next t_check.
        await sp(False)
        await sleep_ms(60)
        assert (await w.s())["resync"]["suspended"] is False
