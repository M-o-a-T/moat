"""
Test the random-walk fake ADC
"""

from __future__ import annotations

import anyio
import pytest

from moat.micro.part.pwm import PWM


class FPWM(PWM):
    "Monkeyhacked PWM class"

    def __init__(self, min, max, base):  # noqa:A002
        self.__xstate = None
        self.min = min
        self.max = max
        self.base = base
        self.val = 0
        self.is_on = False
        self.t_last = 0
        self.__t = 0
        self.evt = anyio.Event()

    async def setup(self):
        "duh"
        pass

    async def run(self):
        "duh"
        pass

    async def ps(self, state: bool) -> None:
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
