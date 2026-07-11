"""Worker-level tests for moat.link.wago.run_out side effects."""

from __future__ import annotations

import anyio
import pytest
from unittest.mock import AsyncMock, MagicMock

from moat.lib.path import P
from moat.link.meta import MsgMeta
from moat.link.wago import worker as wago_worker
from moat.link.wago.model import WagoPort


def _make_entry(**data) -> WagoPort:
    """Build a WagoPort with given config overlay."""
    defaults = {
        "mode": "write",
        "src": ("cmd", "x"),
    }
    defaults.update(data)
    e = WagoPort()
    e.set_((), defaults, MsgMeta(origin="t", timestamp=1))
    return e


class _WatchCtx:
    """Fake d_watch async context manager.

    Items are 3-tuples ``(delay, val)``.  Yields the value directly.
    """

    def __init__(self, items):
        self._items = items

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        pass

    async def __aiter__(self):
        for delay, val in self._items:
            if delay:
                await anyio.sleep(delay)
            yield val


def _link_with(values):
    """Build a fake LinkSender with a ``d_watch``."""
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx(values))
    link.d_set = AsyncMock(return_value=None)
    return link


@pytest.mark.trio
async def test_out_write_passes_through(monkeypatch, autojump_clock):  # noqa:ARG001
    """Basic write mode forwards values to the Wago server."""
    entry = _make_entry()
    link = _link_with([(0, True), (0, False)])
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    srv.find_monitor = AsyncMock(return_value=None)

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            1,
            3,
            P("input.1.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert srv.write_output.call_count == 2
    srv.write_output.assert_any_call(1, 3, True)
    srv.write_output.assert_any_call(1, 3, False)


@pytest.mark.trio
async def test_out_write_with_state(monkeypatch, autojump_clock):  # noqa:ARG001
    """Write mode also writes to the state path when configured."""
    entry = _make_entry(state=("state", "x"))
    link = _link_with([(0, True)])
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    srv.find_monitor = AsyncMock(return_value=None)

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            1,
            3,
            P("input:1:3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    link.d_set.assert_called_once_with(P("state.x"), True)


@pytest.mark.trio
async def test_out_oneshot(monkeypatch, autojump_clock):  # noqa:ARG001
    """Oneshot mode triggers a timed output when value is True."""
    entry = _make_entry(mode="oneshot", t_on=1.5)
    link = _link_with([(0, True)])
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    work = MagicMock()
    work.wait = AsyncMock(return_value=None)
    srv.write_timed_output = MagicMock(return_value=_FakeCtx(work))
    srv.read_output = AsyncMock(return_value=False)
    srv.find_monitor = AsyncMock(return_value=None)

    async with anyio.create_task_group() as tg:
        link.link.tg = tg
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            1,
            3,
            P("input:1:3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    srv.write_timed_output.assert_called_once_with(1, 3, True, 1.5)


@pytest.mark.trio
async def test_out_oneshot_resume(monkeypatch, autojump_clock):  # noqa:ARG001
    """Oneshot mode resumes an existing monitor on startup."""
    entry = _make_entry(mode="oneshot", t_on=1.5)
    link = _link_with([])  # no MoaT-Link changes
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    srv.write_timed_output = MagicMock()
    srv.read_output = AsyncMock(return_value=False)

    resumed = MagicMock()
    resumed.wait = AsyncMock(return_value=None)
    resumed_mon = _FakeCtx(resumed)
    srv.find_monitor = AsyncMock(return_value=resumed_mon)

    async with anyio.create_task_group() as tg:
        link.link.tg = tg
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            2,
            4,
            P("output:2:4"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    srv.find_monitor.assert_awaited_once_with(2, 4)
    srv.write_timed_output.assert_not_called()
    resumed.wait.assert_awaited_once()


@pytest.mark.trio
async def test_out_pulse_resume(monkeypatch, autojump_clock):  # noqa:ARG001
    """Pulse mode resumes an existing monitor on startup."""
    entry = _make_entry(mode="pulse", t_on=0.5, t_off=0.5)
    link = _link_with([])  # no MoaT-Link changes
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    srv.write_pulsed_output = MagicMock()
    srv.read_output = AsyncMock(return_value=False)

    resumed = MagicMock()
    resumed.wait = AsyncMock(return_value=None)
    resumed_mon = _FakeCtx(resumed)
    srv.find_monitor = AsyncMock(return_value=resumed_mon)

    async with anyio.create_task_group() as tg:
        link.link.tg = tg
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            2,
            4,
            P("output:2:4"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    srv.find_monitor.assert_awaited_once_with(2, 4)
    srv.write_pulsed_output.assert_not_called()
    resumed.wait.assert_awaited_once()


class _FakeCtx:
    """Fake async context manager for timed/pulsed output."""

    def __init__(self, work):
        self._work = work

    async def __aenter__(self):
        return self

    @property
    def wait(self):
        return self._work.wait

    async def __aexit__(self, *_a):
        pass


class _BlockingWork:
    """Fake timed-output work whose ``wait()`` blocks until ``fire()``."""

    def __init__(self):
        self._evt = anyio.Event()

    async def wait(self):
        await self._evt.wait()

    def fire(self):
        self._evt.set()


@pytest.mark.trio
async def test_out_oneshot_clears_state_on_expire(monkeypatch, autojump_clock):  # noqa:ARG001
    """A one-shot's state path is cleared when the timer expires."""
    entry = _make_entry(mode="oneshot", t_on=1.5, state=("state", "x"))
    link = _link_with([(0, True)])
    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    work = MagicMock()
    work.wait = AsyncMock(return_value=None)  # timer fires immediately
    srv.write_timed_output = MagicMock(return_value=_FakeCtx(work))
    srv.read_output = AsyncMock(return_value=False)  # at rest after expiry
    srv.find_monitor = AsyncMock(return_value=None)

    async with anyio.create_task_group() as tg:
        link.link.tg = tg
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            1,
            3,
            P("input:1:3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    calls = [c.args for c in link.d_set.call_args_list]
    assert (P("state.x"), True) in calls
    assert (P("state.x"), False) in calls


@pytest.mark.trio
async def test_out_oneshot_retrigger_keeps_state_cleared(monkeypatch, autojump_clock):  # noqa:ARG001
    """Re-triggering a one-shot must not leave its state stuck on.

    The cancelled instance's shielded state reconciliation must finish
    (and signal done) *before* the new instance starts, so a stale
    ``d_set(state, True)`` cannot land after the new instance's expiry
    clear. The first ``read_output`` is slowed to widen the race window;
    it returns ``True`` to stand in for reading the wire while the new
    one-shot holds it set.
    """
    entry = _make_entry(mode="oneshot", t_on=0.1, state=("state", "x"))
    link = _link_with([(0, True), (0.05, True)])

    srv = MagicMock()
    srv.write_output = AsyncMock(return_value=None)
    srv.find_monitor = AsyncMock(return_value=None)

    created: list[_BlockingWork] = []

    def make_ctx(*_a):
        w = _BlockingWork()
        created.append(w)
        return _FakeCtx(w)

    srv.write_timed_output = MagicMock(side_effect=make_ctx)

    seq: list[bool] = []

    async def d_set(_path, val):
        seq.append(bool(val))

    link.d_set = AsyncMock(side_effect=d_set)

    ro_seen: list[int] = []

    async def read_output(_card, _port):
        ro_seen.append(len(ro_seen) + 1)
        if len(ro_seen) == 1:
            await anyio.sleep(1.0)  # slow: delays the cancelled instance's write
            return True
        return False

    srv.read_output = read_output

    async with anyio.create_task_group() as tg:
        link.link.tg = tg
        tg.start_soon(
            wago_worker.run_out,
            link,
            srv,
            entry,
            1,
            3,
            P("input:1:3"),
        )
        await anyio.sleep(0.06)  # let the first trigger start, then re-trigger
        for _ in range(400):
            if len(created) >= 2:
                break
            await anyio.sleep(0.05)
        assert len(created) >= 2, "second one-shot never started"
        created[1].fire()  # expire the current one-shot
        await anyio.sleep(2.0)  # let the slow reconciliation finish
        tg.cancel_scope.cancel()

    assert any(seq), "state was never set"
    assert seq[-1] is False, "state was not cleared after re-trigger"
