"""Worker-level tests for moat.link.knx.run_out state-suppression logic."""

from __future__ import annotations

import anyio
import pytest
from unittest.mock import AsyncMock, MagicMock

from moat.lib.path import P
from moat.lib.xknx.telegram import GroupAddress
from moat.link.knx import worker as knx_worker
from moat.link.knx.model import KnxEntry
from moat.link.meta import MsgMeta


def _make_entry(**data) -> KnxEntry:
    """Build a KnxEntry with given config overlay."""
    defaults = {
        "type": "out",
        "mode": "binary",
        "src": ("cmd", "x"),
    }
    defaults.update(data)
    e = KnxEntry()
    e.set_((), defaults, MsgMeta(origin="t", timestamp=1))
    return e


class _WatchCtx:
    """Fake d_watch async context manager.

    Items are 3-tuples ``(delay, val, meta)``.  Yields ``None`` when
    ``val`` is ``None`` (used to simulate ``mark=True``'s end-of-initial
    sentinel); otherwise yields ``(val, meta)``.
    """

    def __init__(self, items):
        self._items = items

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        pass

    async def __aiter__(self):
        for delay, val, meta in self._items:
            if delay:
                await anyio.sleep(delay)
            if val is None and meta is None:
                yield None
            else:
                yield val, meta


def _link_with(values, getter=None):
    """Build a fake LinkSender with a ``d_watch``/``d_get`` pair."""
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx(values))
    if getter is None:

        async def _get(_path, meta=False):  # noqa: ARG001
            raise KeyError(_path)

        link.d_get = AsyncMock(side_effect=_get)
    else:
        link.d_get = AsyncMock(side_effect=getter)
    return link


def _patch_device(monkeypatch, sets):
    """Replace _make_out_device so we can observe set_val calls."""
    device = MagicMock()

    async def _set(_dev, val):
        sets.append(val)

    monkeypatch.setattr(
        knx_worker,
        "_make_out_device",
        lambda *_a, **_k: (device, _set, lambda _d: None),
    )
    return device


@pytest.mark.trio
async def test_out_no_state_passes_through(monkeypatch, autojump_clock):  # noqa:ARG001
    """Without a ``state`` path every command is forwarded."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry()  # no state
    link = _link_with([(0, True, MsgMeta(origin="t", timestamp=10))])
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [True]


@pytest.mark.trio
async def test_out_state_older_passes(monkeypatch, autojump_clock):  # noqa:ARG001
    """State older than the command: command goes through."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry(state=("state", "x"))

    async def _get(_path, meta=False):  # noqa: ARG001
        return False, MsgMeta(origin="bus", timestamp=5)

    link = _link_with(
        [(0, True, MsgMeta(origin="t", timestamp=10))],
        getter=_get,
    )
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [True]


@pytest.mark.trio
async def test_out_state_newer_suppresses(monkeypatch, autojump_clock):  # noqa:ARG001
    """State newer than the command: command is suppressed."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry(state=("state", "x"))

    async def _get(_path, meta=False):  # noqa: ARG001
        return False, MsgMeta(origin="bus", timestamp=20)

    link = _link_with(
        [(0, True, MsgMeta(origin="t", timestamp=10))],
        getter=_get,
    )
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == []


@pytest.mark.trio
async def test_out_state_missing_passes(monkeypatch, autojump_clock):  # noqa:ARG001
    """A missing state entry is treated as 'no last-known state', allow."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry(state=("state", "x"))
    link = _link_with([(0, True, MsgMeta(origin="t", timestamp=10))])  # default getter -> KeyError
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [True]


@pytest.mark.trio
async def test_out_state_only_blocks_old(monkeypatch, autojump_clock):  # noqa:ARG001
    """Mixed sequence: stale cmd suppressed, fresh cmd forwarded."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry(state=("state", "x"))

    async def _get(_path, meta=False):  # noqa: ARG001
        return False, MsgMeta(origin="bus", timestamp=20)

    link = _link_with(
        [
            (0, True, MsgMeta(origin="t", timestamp=10)),  # stale -> drop
            (0, False, MsgMeta(origin="t", timestamp=30)),  # fresh -> pass
        ],
        getter=_get,
    )
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [False]


@pytest.mark.trio
async def test_out_state_check_only_during_initial(monkeypatch, autojump_clock):  # noqa:ARG001
    """After the ``mark=True`` sentinel runtime updates skip the state check.

    A post-mark command whose timestamp predates the state must still be
    forwarded, and the state path must not be queried.
    """
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry(state=("state", "x"))

    get_calls: list = []

    async def _get(_path, meta=False):  # noqa: ARG001
        get_calls.append(_path)
        return False, MsgMeta(origin="bus", timestamp=100)

    link = _link_with(
        [
            (0, True, MsgMeta(origin="t", timestamp=10)),  # initial, stale -> drop
            (0, None, None),  # end-of-initial marker
            (0, False, MsgMeta(origin="t", timestamp=20)),  # runtime, no check -> pass
        ],
        getter=_get,
    )
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [False]
    # state was consulted exactly once, for the initial command.
    assert len(get_calls) == 1


@pytest.mark.trio
async def test_out_no_state_skips_mark(monkeypatch, autojump_clock):  # noqa:ARG001
    """Without ``state`` the watcher is opened with ``mark=False``."""
    sets: list = []
    _patch_device(monkeypatch, sets)
    entry = _make_entry()
    link = _link_with([(0, True, MsgMeta(origin="t", timestamp=10))])
    srv = MagicMock()
    srv.devices = MagicMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            knx_worker.run_out,
            link,
            srv,
            entry,
            GroupAddress("1/2/3"),
            P("k.1.2.3"),
        )
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert sets == [True]
    _, kwargs = link.d_watch.call_args
    assert kwargs.get("mark") is False
