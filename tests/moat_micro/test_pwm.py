"""
Test the PWM implementation: cycling tests of the timing core.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.micro.part.pwm import PWM, _Send


class FPWM(PWM):
    "Monkeyhacked PWM class — exercises calc_times/_measure without RPC."

    def __init__(self, min, max):  # noqa:A002
        self.__xstate = None
        self.min = min
        self.max = max
        self.value = 0.0
        self.t_on = 0
        self.t_off = 0
        self.is_on = False
        self.t_last = 0
        self.__t = 0
        self.evt = anyio.Event()
        self.ps = _Send(self._ps)

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
    p = FPWM(1, 10)
    p.set_times(0.1)
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
    p = FPWM(1, 10)
    p.set_times(0.9)
    await p.step(1, 9, True)
    await p.step(1, 8, None)
    await p.step(7, 1, None)
    await p.step(1, 1, False)
    await p.step(1, 9, True)


@pytest.mark.anyio
async def test_onoff():
    "on/off test"
    p = FPWM(3, 10)
    p.set_times(0.99)
    await p.step(2, 1, None)
    await p.step(1, None, True)
    p.set_times(0.01)
    await p.step(2, 1, None)
    await p.step(1, None, False)
    p.set_times(0.5)
    await p.step(1, 2, None)
    await p.step(2, 3, True)
    await p.step(1, 2, None)
    await p.step(2, 3, False)


# ---------------------------------------------------------------------------
# End-to-end tests using rpc_stack + _fake.Pin
# ---------------------------------------------------------------------------
# Config: min=50 ms, max=500 ms, input is in [0..1]
#   val=0.5 → t_on=50 ms, t_off=50 ms
#   val=0.25 → t_on=50 ms, t_off=150 ms
#   val=0.0  → t_on=0  (always off; settles to "wait for event")
#   val=1.0  → t_off=0 (always on after min=50 ms)
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
p:
  app: _fake.Pin
  pin: X
"""


@pytest.mark.anyio
async def test_e2e_half(tmp_path):
    "50 % duty cycle: pin alternates every 50 ms"
    async with rpc_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Anchor in a known-off state so t_last is fresh and td > t_off=50 ms.
        await w.w(0.0)
        await sleep_ms(70)
        assert False is await p()

        # val=0.5 → t_on=t_off=50 ms.  td≈70 ms ≥ t_off → event fires at once.
        await w.w(0.5)
        await sleep_ms(20)  # let the scheduler switch the pin on
        assert True is await p()

        await sleep_ms(60)  # 80 ms after w.w(0.5): past t_on=50 ms → off
        assert False is await p()

        await sleep_ms(60)  # 140 ms after w.w(0.5): past t_off=50 ms → on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_always_off(tmp_path):
    "val=0 keeps the pin off permanently"
    async with rpc_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        await w.w(0.0)
        await sleep_ms(70)
        assert False is await p()
        await sleep_ms(100)
        assert False is await p()


@pytest.mark.anyio
async def test_e2e_always_on(tmp_path):
    "val=1 turns the pin on after min=50 ms and keeps it on"
    async with rpc_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        await w.w(1.0)
        # The min timer has not yet elapsed; the wakeup event was set by
        # set_times (t_off=0 → td≥0 always), but _measure still sees
        # td < min and returns dly=50 ms rather than switching on.
        assert False is await p()

        await sleep_ms(70)  # past min=50 ms → pin on
        assert True is await p()

        await sleep_ms(100)  # stays on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_asymmetric(tmp_path):
    "val=0.25 → t_on=50 ms, t_off=150 ms"
    async with rpc_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))
        p = d.sub_at(P("p"))

        # Anchor: let always-off run for 200 ms so that t_last is old enough
        # that td > t_off=150 ms when we switch to val=0.25.
        await w.w(0.0)
        await sleep_ms(200)
        assert False is await p()

        # td≈200 ms ≥ t_off=150 ms → wakeup event fires immediately.
        await w.w(0.25)
        await sleep_ms(20)  # let the scheduler switch the pin on
        assert True is await p()

        await sleep_ms(60)  # 80 ms after w.w(0.25): past t_on=50 ms → off
        assert False is await p()

        await sleep_ms(160)  # 240 ms after w.w(0.25): past t_off=150 ms → on
        assert True is await p()


@pytest.mark.anyio
async def test_e2e_state(tmp_path):
    "cmd_s returns a well-formed state dict with correct on/off times"
    async with rpc_stack(tmp_path, E2E_CFG) as d:
        w = d.sub_at(P("w"))

        await w.w(0.5)
        s = await w.s()
        assert s["val"] == 0.5
        assert s["on"] == 50
        assert s["off"] == 50
        assert isinstance(s["p"], bool)
