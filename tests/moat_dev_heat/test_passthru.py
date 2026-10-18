"""
Tests for the passthru unit (HEAT.md §2.8).
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven
from moat.dev.heat.config import make_config
from moat.dev.heat.passthru import (
    IDLE,
    SENSORS,
    SOLVIS,
    PassthruCfg,
    PassthruCore,
    PassthruState,
    PassthruUnit,
    passthru,
)
from moat.dev.heat.sim.paths import INPUT_PATHS
from moat.dev.heat.state import state_path
from moat.lib.path import P

from typing import Any

STATE = state_path("passthru")
REQUEST = P("app.heat.passthru.request")
POWER = P("heat.s.pump.power")
COMPR = P("heat.s.pump.compr.speed")
PUMP_OUT = P("app.heat.pump.out")
ERR = P("app.modbus.tcp.solvis.502")
MODE = INPUT_PATHS["hp_mode"]
POWER_CMD = INPUT_PATHS["hp_power"]
PWM = INPUT_PATHS["pwm"]
RATE = P("heat.s.pump.rate.cmd")
OVR_WP = P("app.heat.override.wp")
T_IN = P("heat.s.pump.temp.in")
T_OUT = P("heat.s.pump.temp.out")


class Run:
    "a passthru core with inputs that can be changed step by step"

    def __init__(self, item: Any = NotGiven, state: PassthruState | None = None) -> None:
        cfg = make_config("passthru", PassthruCfg, item)
        self.core = PassthruCore(cfg, state or PassthruState(), 0)
        self.now = 0.0
        self.inputs: dict[str, Any] = {
            "request": None,
            "pump": {"run": "off"},
            "m_power": 0.1,
            "compr": 0,
            "error_0": {},
        }
        self.res: Any = None

    def step(self, **kw: Any) -> tuple[bool, str | None]:
        "advance by a second, with changed inputs; returns the state"
        self.now += 1
        self.inputs.update(kw)
        self.res = self.core.step(self.inputs, self.now)
        st = self.core.state
        return st.bypass, st.switching


def test_idle_switch() -> None:
    "with an idle heat pump, both directions switch at once"
    r = Run()
    assert r.step() == (False, None)
    assert r.step(request=True) == (True, None)
    assert r.res.save_now
    assert r.step() == (True, None)
    assert not r.res.save
    assert r.step(request=False) == (False, None)


def test_deferred_while_running() -> None:
    "a request waits while the heat pump runs, in either direction"
    r = Run()
    assert r.step(request=True, m_power=3.0, pump={"run": "run"}) == (False, IDLE)
    assert r.step(m_power=0.5) == (False, IDLE)  # our pump unit still runs
    assert r.step(pump={"run": "down"}) == (False, IDLE)
    assert r.step(pump={"run": "off"}) == (True, None)
    # the Solvis runs it now
    assert r.step(request=False, m_power=2.5, compr=40) == (True, IDLE)
    assert r.step(m_power=0.2) == (True, IDLE)  # compressor still on
    assert r.step(compr=0) == (False, None)


def test_withdrawn() -> None:
    "a request withdrawn while waiting is forgotten"
    r = Run()
    assert r.step(request=True, m_power=3.0) == (False, IDLE)
    assert r.step(request=False) == (False, None)
    assert r.step(m_power=0.0) == (False, None)


def test_sensors() -> None:
    "a missing reading blocks the switch"
    r = Run()
    assert r.step(request=True, m_power=None) == (False, SENSORS)
    assert r.step(m_power=0.0, compr=None) == (False, SENSORS)
    assert r.step(compr=0) == (True, None)


def test_no_compressor() -> None:
    "without a compressor reading, the power decides"
    r = Run({"compr": None})
    del r.inputs["compr"]
    assert r.step(request=True) == (True, None)


def test_emergency_end() -> None:
    "a Solvis poll error ends the bypass at once and resets the request"
    r = Run()
    r.step(request=True)
    assert r.step(m_power=3.0, compr=40) == (True, None)
    assert r.step(error_0={P("1.1sec"): {"exc": "TimeoutError"}}) == (False, None)
    assert r.res.outputs == {REQUEST: False}
    assert r.res.save_now
    # the request is gone; a new one waits until the error is
    assert r.step(request=False) == (False, None)
    assert r.step(request=True, m_power=0.0, compr=0) == (False, SOLVIS)
    assert r.step(error_0={}) == (True, None)


def test_restart() -> None:
    "a new core resumes from the saved state"
    r = Run(state=PassthruState(bypass=True))
    assert r.step(request=True) == (True, None)
    assert not r.res.save


@pytest.mark.parametrize(
    ("value", "res"),
    [
        (None, False),
        ({"bypass": False, "switching": None}, False),
        ({"bypass": True, "switching": None}, True),
        ({"bypass": True, "switching": IDLE}, True),
        ("original", False),
    ],
)
def test_passthru(value: Any, res: bool) -> None:
    "the helper for other units"
    assert passthru(value) is res


# on MoaT-Link


@pytest.mark.anyio
async def test_unit(heat) -> None:
    "switching, restart in the bypassed state, emergency end"
    await heat.seed_config("passthru", {"errors": [ERR]})
    await heat.feed(PUMP_OUT, {"run": "off"})
    await heat.feed(POWER, 0.1)
    await heat.feed(COMPR, 0)
    u = await heat.run_unit(PassthruUnit)
    await heat.feed(REQUEST, True)
    await heat.expect(STATE, passthru)

    # restart: still bypassed, nothing written
    u.cancel()
    u = await heat.run_unit(PassthruUnit)
    await heat.feed(POWER, 3.0)
    await heat.expect(STATE, lambda v: v == {"bypass": True, "switching": None})

    # the Solvis can't be polled: out at once, request reset
    await heat.feed(P("error") + ERR, {"exc": "TimeoutError"})
    await heat.expect(STATE, lambda v: v == {"bypass": False, "switching": None})
    await heat.expect(REQUEST, lambda v: v is False)
