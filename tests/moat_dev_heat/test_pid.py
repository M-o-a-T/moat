"""
Tests for the heat controller's PID wrapper.
"""

from __future__ import annotations

import pytest

from moat.dev.heat.pid import APID, T_OFFSET, PIDCfg, PIDLog, PIDState
from moat.dev.heat.state import State, StateStore, state_path
from moat.lib.path import P
from moat.util.time import loop_time, time

CFG = PIDCfg(p=0.1, i=0.01, min=-100, max=100, rebase_after=300)
EPOCH = 1_700_000_000.0


def _persist(st: PIDState) -> dict:
    "save as if wall-clock time were ``EPOCH`` + monotonic time"
    return st.model_dump(context={T_OFFSET: EPOCH})


def _restore(data: dict, wall: float, mono: float) -> PIDState:
    "load after a restart, at wall-clock time ``wall`` and monotonic time ``mono``"
    return PIDState.model_validate(data, context={T_OFFSET: wall - mono})


def _ref(steps: list[float]) -> PIDState:
    "an uninterrupted run with steps at the given times"
    st = PIDState()
    pid = APID(CFG, st, now=steps[0])
    pid.setpoint(25)
    for t in steps:
        pid(20.0, t)
    return st


def test_error_sign():
    "the input is the measurement: below the setpoint, the output rises"
    pid = APID(CFG, PIDState(), now=0)
    pid.setpoint(25)
    a = pid(20.0, 0)
    b = pid(20.0, 10)
    assert 0 < a < b
    assert pid(30.0, 20) < b


def test_persist_restore():
    "state survives a restart with a different monotonic clock"
    st = _ref([100, 110, 120, 130, 140])
    data = _persist(st)
    assert data["t"] == EPOCH + 140

    # restarted 30 s later; the new monotonic clock reads 5
    st2 = _restore(data, EPOCH + 170, 5)
    assert st2.t == -25
    pid2 = APID(CFG, st2, now=5)
    assert st2.setpoint == 25

    # the next step integrates over the whole gap
    pid2(20.0, 15)
    ref = _ref([100, 110, 120, 130, 140, 180])
    assert st2.i == pytest.approx(ref.i)


def test_no_jump_after_long_outage():
    "an old timestamp is re-based, so there's no integrator jump"
    st = _ref([100, 110, 120, 130, 140])
    st2 = _restore(_persist(st), EPOCH + 140 + 3600, 7)
    pid2 = APID(CFG, st2, now=7)
    assert st2.t == 7
    pid2(20.0, 17)
    ref = _ref([100, 110, 120, 130, 140, 150])
    assert st2.i == pytest.approx(ref.i)


def test_logging():
    "setpoint and output are offered for publishing"
    cfg = PIDCfg(p=0.1, max=1, log=PIDLog(value=P("x.val"), setpoint=P("x.set")))
    pid = APID(cfg, PIDState(), now=0)
    pid.setpoint(25)
    out = pid(20.0, 10)
    assert pid.logs == {P("x.set"): 25, P("x.val"): out}


class _TState(State):
    "unit state containing a PID"

    load: PIDState = PIDState()


@pytest.mark.anyio
async def test_state_store_wall_time(link):
    "the store persists PID timestamps as wall-clock time"
    ss = StateStore(link, "test", _TState)
    s = await ss.load()
    now = loop_time()
    pid = APID(CFG, s.load, now=now)
    pid.setpoint(25)
    pid(20.0, now)
    await ss.save()
    await link.i_sync()

    data = await link.d_get(state_path("test"))
    assert data["load"]["t"] == pytest.approx(time(), abs=5)

    s2 = await StateStore(link, "test", _TState).load()
    assert s2.load.t == pytest.approx(now, abs=0.5)
