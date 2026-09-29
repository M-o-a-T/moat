"""
Tests for the heat controller's persistent state.
"""

from __future__ import annotations

import anyio
import pytest

from moat.dev.heat.state import State, StateStore, state_path

pytestmark = pytest.mark.anyio

UNIT = "test"


class TState(State):
    "test state"

    run: int = 0
    last: float = 1.5


async def _stored(link) -> dict | None:
    await link.i_sync()
    try:
        return await link.d_get(state_path(UNIT))
    except KeyError:
        return None


async def test_defaults_and_restore(link):
    "defaults on first run; a new store restores the saved state"
    st = StateStore(link, UNIT, TState, save_delay=0.1)
    s = await st.load()
    assert s == TState()

    s.run = 3
    await st.save()

    st2 = StateStore(link, UNIT, TState)
    s2 = await st2.load()
    assert s2.run == 3
    assert s2.last == 1.5


async def test_invalid_state(link):
    "invalid stored state is replaced by defaults"
    await link.d_set(state_path(UNIT), {"run": "bad"}, retain=True, verify=False)
    await link.i_sync()
    st = StateStore(link, UNIT, TState)
    assert await st.load() == TState()


async def test_debounce(link):
    "changes are collected for `save_delay` seconds"
    st = StateStore(link, UNIT, TState, save_delay=0.5)
    await st.load()
    async with anyio.create_task_group() as tg:
        await tg.start(st.run)
        st.state.run = 1
        st.changed()
        await anyio.sleep(0.1)
        st.state.run = 2
        st.changed()
        await anyio.sleep(0.1)
        assert await _stored(link) is None

        await anyio.sleep(0.6)
        assert (await _stored(link))["run"] == 2
        tg.cancel_scope.cancel()


async def test_immediate(link):
    "an immediate change is written at once"
    st = StateStore(link, UNIT, TState, save_delay=10)
    await st.load()
    async with anyio.create_task_group() as tg:
        await tg.start(st.run)
        st.state.run = 5
        st.changed(immediate=True)
        await anyio.sleep(0.2)
        assert (await _stored(link))["run"] == 5
        tg.cancel_scope.cancel()


async def test_flush_on_exit(link):
    "pending changes are written when the saver ends"
    st = StateStore(link, UNIT, TState, save_delay=10)
    await st.load()
    async with anyio.create_task_group() as tg:
        await tg.start(st.run)
        st.state.run = 7
        st.changed()
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()
    assert (await _stored(link))["run"] == 7


def test_mono_time_across_reboot() -> None:
    "monotonic timestamps are persisted as wall-clock time, so a reboot doesn't break them"
    from moat.dev.heat.pid import T_OFFSET  # noqa: PLC0415
    from moat.dev.heat.pump import PumpState  # noqa: PLC0415

    wall = 1_800_000_000.0
    # before: monotonic 5000 at wall time `wall`; t_load was 100 s ago
    st = PumpState(t_load=4900.0, t_run=4000.0, t_change=4950.0)
    data = st.model_dump(context={T_OFFSET: wall - 5000})
    assert data["t_load"] == wall - 100
    # after a reboot, 60 s later: monotonic 30
    st2 = PumpState.model_validate(data, context={T_OFFSET: wall + 60 - 30})
    assert st2.t_load == pytest.approx(30 - 160)
    assert st2.t_run == pytest.approx(30 - 1060)
    assert st2.t_change == pytest.approx(30 - 110)
