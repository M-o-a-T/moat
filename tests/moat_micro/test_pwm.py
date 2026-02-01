"""
Test the random-walk fake ADC
"""
# ruff:noqa:SLF001

from __future__ import annotations

import anyio
import pytest
from unittest.mock import patch

import moat.micro.part.pwm as pwm_module
from moat.micro.part.pwm import PWM, _Send


class FPWM(PWM):
    "Monkeyhacked PWM class"

    def __init__(self, min, max, base, vmin=None, vmax=None, resync=0):  # noqa:A002
        self.__xstate = None
        self.min = min
        self.max = max
        self.base = base
        self.vmin = vmin
        self.vmax = vmax
        self.resync = resync
        self.t_on = 0
        self.t_off = 0
        self.is_on = False
        self.t_last = 0
        self.__t = 0
        self.evt = anyio.Event()
        self.ps = _Send(self._ps)
        # Resync state
        self._out_time = 0
        self._out_on = None
        self._resync_left = 0
        self._resync_on = None
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
async def test_resync_from_low():
    "Test resync when transitioning from below vmin to in range"
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(3, 10, 100, vmin=10, resync=100)

        # Start below vmin - should turn off
        p.set_times(5)  # below vmin=10
        assert p.t_on == 0
        assert p.t_off == 10
        assert p._out_on is False  # below vmin = output off

        # Run _measure to accumulate out-of-range time
        # is_on=False already, t_on=0, so no switch needed
        p.set_time(0)
        await p.step(0, 3, None)  # wait for min delay, no state change (already off)

        # After min delay, switch to off (but already off, so no state change)
        await p.step(3, None, None)  # t_on=0 means dly=None (wait forever)

        # Accumulate more time
        await p.step(47, None, None)
        assert p._out_time == 50

        # Go into range - should start resync
        mock_time = 50
        p.set_times(50)  # in range
        assert p._resync_left == 50  # accumulated out_time
        assert p._resync_on is True  # was off, so resync ON
        assert p._out_on is None

        # During resync, output should be forced ON
        await p.step(0, 50, True)  # resync remaining = 50ms, output forced ON

        # After 25ms more, still in resync
        await p.step(25, 25, None)  # resync remaining = 25ms, no change

        # After resync completes, normal PWM starts with t_last reset
        await p.step(25, 3, None)  # resync done, td=0, delay=t_on=3

        # Normal PWM: after t_on=3ms, switch to OFF
        await p.step(3, 3, False)  # td=3 >= t_on=3, switch OFF

        # After t_off=3ms, switch to ON
        await p.step(3, 3, True)  # td=3 >= t_off=3, switch ON


@pytest.mark.anyio
async def test_resync_from_high():
    "Test resync when transitioning from above vmax to in range"
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(3, 10, 100, vmax=90, resync=100)

        # Start above vmax - should turn on permanently
        p.set_times(95)  # above vmax=90
        assert p.t_on == 10
        assert p.t_off == 0
        assert p._out_on is True  # above vmax = output on

        # Run _measure to accumulate out-of-range time
        # is_on=False initially, so first call will wait for min delay then switch on
        p.set_time(0)
        await p.step(0, 3, None)  # wait for min delay first

        # After min delay, switch to on
        await p.step(3, None, True)  # t_off=0 means dly=None (wait forever)

        # Accumulate more time (77ms more = 80 total)
        await p.step(77, None, None)
        assert p._out_time == 80

        # Go into range - should start resync
        mock_time = 80
        p.set_times(50)  # in range
        assert p._resync_left == 80  # accumulated out_time
        assert p._resync_on is False  # was on, so resync OFF
        assert p._out_on is None

        # During resync, output should be forced OFF
        await p.step(0, 80, False)  # resync remaining = 80ms, output forced OFF


@pytest.mark.anyio
async def test_resync_cancelled_by_going_out_of_range():
    "Test that resync is cancelled if value goes back out of range"
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(3, 10, 100, vmin=10, resync=100)

        # Start below vmin
        p.set_times(5)
        assert p._out_on is False

        # Run _measure to accumulate out-of-range time
        p.set_time(0)
        await p.step(0, 3, None)  # wait for min delay first
        await p.step(3, None, None)  # now at t=3, switch happens (but already off)
        await p.step(47, None, None)  # accumulate more time
        assert p._out_time == 50

        # Go into range, start resync
        mock_time = 50
        p.set_times(50)
        assert p._resync_left == 50
        assert p._resync_on is True

        # Go back below vmin during resync - should cancel resync
        mock_time = 60
        p.set_times(5)
        assert p._resync_left == 0
        assert p._resync_on is None
        assert p._out_on is False  # back to out-of-range (below vmin)
        assert p._out_time == 0  # reset
        assert p.t_on == 0


@pytest.mark.anyio
async def test_resync_limited_by_off_time():
    "Test that resync time is limited by actual off duration"
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(3, 10, 100, vmin=10, resync=1000)  # long resync

        # Start below vmin
        p.set_times(5)

        # Run _measure to accumulate out-of-range time (only 30ms)
        p.set_time(0)
        await p.step(0, 3, None)  # wait for min delay first
        await p.step(3, None, None)  # switch happens (but already off)
        await p.step(27, None, None)  # accumulate more time (3+27=30)
        assert p._out_time == 30  # only 30ms accumulated

        # Go into range
        mock_time = 30
        p.set_times(50)
        # Resync should be limited to 30ms (accumulated), not 1000ms (max)
        assert p._resync_left == 30
