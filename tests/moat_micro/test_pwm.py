"""
Test the PWM resync logic.
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
async def test_resync_low_fixed_ratio():
    "Resync from low clamps to the configured ratio until the timer ends."
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
        assert p._out_mode == "low"
        assert p.t_on == 0
        assert p.t_off == 10

        mock_time = 0
        p.set_times(20)
        assert p._sync_active == "low"
        assert p._sync_left == 50
        assert p.t_on == 1
        assert p.t_off == 1

        p.set_time(0)
        mock_time = 1
        await p.step(1, 1, True)
        assert p._sync_left == 49

        mock_time = 50
        await p.step(49, 4, False)
        assert p._sync_active is None
        assert p.t_off == 4


@pytest.mark.anyio
async def test_resync_high_fixed_ratio():
    "Resync from high clamps to the configured ratio until the timer ends."
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        p = FPWM(
            1,
            10,
            100,
            sync_high={"threshold": 90, "input": 20, "t_sync": 0.05},
        )

        p.set_times(95)
        assert p._out_mode == "high"
        assert p.t_on == 10
        assert p.t_off == 0

        mock_time = 0
        p.set_times(80)
        assert p._sync_active == "high"
        assert p._sync_left == 50
        assert p.t_on == 1
        assert p.t_off == 4

        p.set_time(0)
        mock_time = 4
        await p.step(4, 1, True)

        mock_time = 50
        await p.step(46, 1, False)
        assert p._sync_active is None
        assert p.t_on == 4
        assert p.t_off == 1


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


@pytest.mark.anyio
async def test_resync_suspended_by_sync_path():
    "Sync path readings can suspend and resume the resync clamp."
    mock_time = 0

    def fake_ticks_ms():
        return mock_time

    class SyncProbe:
        def __init__(self, value: float):
            self.value = value

        async def __call__(self) -> float:
            return self.value

    with patch.object(pwm_module, "ticks_ms", fake_ticks_ms):
        probe = SyncProbe(20)
        p = FPWM(
            1,
            10,
            100,
            sync_low={
                "threshold": 10,
                "input": 50,
                "t_sync": 0.05,
                "t_check": 0.01,
                "bound": 10,
            },
            sync_path=probe,
        )

        p.set_times(5)
        p.set_times(20)
        p.set_time(0)

        mock_time = 0
        await p.step(0, 4, None)
        assert p._sync_suspended is True
        assert p.t_off == 4

        probe.value = 0
        mock_time = 10
        await p.step(10, 1, True)
        assert p._sync_suspended is False
        assert p.t_off == 1
