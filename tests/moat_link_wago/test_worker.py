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

    srv.write_timed_output.assert_called_once_with(1, 3, True, 1.5)


class _FakeCtx:
    """Fake async context manager for timed/pulsed output."""

    def __init__(self, work):
        self._work = work

    async def __aenter__(self):
        return self._work

    async def __aexit__(self, *_a):
        pass
