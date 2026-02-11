"""Tests for moat.link.metrics."""

from __future__ import annotations

import anyio
import pytest
from unittest.mock import AsyncMock, MagicMock

from moat.lib.path import P
from moat.link.meta import MsgMeta
from moat.link.metrics import model as metrics_model
from moat.link.metrics.model import MetricsEntry, MetricsRoot, MetricsServer
from moat.link.metrics.worker import run_entry
from moat.link.node import Node

# -- Model tests (sync) ---------------------------------------------------


def test_root_creates_server():
    """MetricsRoot.add_child creates MetricsServer instances."""
    root = MetricsRoot()
    child = root.add_child("srv1")
    assert isinstance(child, MetricsServer)


def test_server_creates_entry():
    """MetricsServer.add_child creates MetricsEntry instances."""
    srv = MetricsServer()
    child = srv.add_child("entry1")
    assert isinstance(child, MetricsEntry)


def test_entry_properties():
    """MetricsEntry properties extract config from stored data."""
    entry = MetricsEntry()
    entry.set_(
        (),
        {
            "source": ("test", "path"),
            "series": "temperature",
            "tags": {"host": "box1"},
            "mode": "gauge",
            "factor": 2.0,
            "offset": -10,
            "t_min": 5.0,
            "attr": ("val",),
        },
        MsgMeta(origin="test", t=1),
    )
    assert entry.source == ("test", "path")
    assert entry.series == "temperature"
    assert entry.tags == {"host": "box1"}
    assert entry.mode == "gauge"
    assert entry.factor == 2.0
    assert entry.offset == -10
    assert entry.t_min == 5.0
    assert entry.attr == ("val",)
    assert entry.is_complete()


def test_entry_incomplete():
    """is_complete returns False when required fields are missing."""
    entry = MetricsEntry()
    assert not entry.is_complete()

    entry.set_((), {"source": ("x",)}, MsgMeta(origin="test", t=1))
    assert not entry.is_complete()  # missing series and tags


def test_node_add_child_public():
    """Node.add_child is the public API (renamed from _add)."""
    n = Node()
    c = n.add_child("x")
    assert isinstance(c, Node)
    with pytest.raises(ValueError, match="exists"):
        n.add_child("x")


# -- Worker tests (async) -------------------------------------------------


class _WatchCtx:
    """Fake d_watch async context manager."""

    def __init__(self, values):
        self._values = values

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def __aiter__(self):
        for delay, val in self._values:
            if delay:
                await anyio.sleep(delay)
            yield val


@pytest.fixture
def recorded_entries():
    """Collect Entry objects sent via _test_hook."""
    entries: list = []
    orig = metrics_model._test_hook  # noqa:SLF001

    def _hook(e) -> None:
        entries.append(e)

    metrics_model._test_hook = _hook  # noqa:SLF001
    yield entries
    metrics_model._test_hook = orig  # noqa:SLF001


def _make_entry(**data) -> MetricsEntry:
    """Create a MetricsEntry with data set."""
    defaults = {
        "source": ("src", "path"),
        "series": "test_series",
        "tags": {"host": "h1"},
        "mode": "gauge",
    }
    defaults.update(data)
    entry = MetricsEntry()
    entry.set_((), defaults, MsgMeta(origin="test", t=1))
    return entry


@pytest.mark.trio
async def test_worker_forwards_values(recorded_entries, autojump_clock):  # noqa:ARG001
    """Worker writes watched values to the backend."""
    entry = _make_entry()
    backend = MagicMock()
    backend.put = AsyncMock()
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx([(0, 10), (0, 20)]))

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_entry, link, entry, backend, P("test"))
        await anyio.sleep(1)
        tg.cancel_scope.cancel()

    assert len(recorded_entries) == 2
    assert recorded_entries[0].value == 10
    assert recorded_entries[1].value == 20


@pytest.mark.trio
async def test_worker_factor_offset(recorded_entries, autojump_clock):  # noqa:ARG001
    """Worker applies factor and offset."""
    entry = _make_entry(factor=2.0, offset=5)
    backend = MagicMock()
    backend.put = AsyncMock()
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx([(0, 10)]))

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_entry, link, entry, backend, P("test"))
        await anyio.sleep(1)
        tg.cancel_scope.cancel()

    assert recorded_entries[0].value == 25  # 10*2+5


@pytest.mark.trio
async def test_worker_t_min_throttle(recorded_entries, autojump_clock):  # noqa:ARG001
    """Worker respects t_min rate limiting."""
    entry = _make_entry(t_min=1.0)
    backend = MagicMock()
    backend.put = AsyncMock()
    link = MagicMock()
    link.d_watch = MagicMock(
        return_value=_WatchCtx([
            (0, 10),  # t=0   → accepted
            (0.3, 20),  # t=0.3 → skipped
            (0.8, 30),  # t=1.1 → accepted
            (0.1, 40),  # t=1.2 → skipped
            (1.5, 50),  # t=2.7 → accepted
        ])
    )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_entry, link, entry, backend, P("test"))
        await anyio.sleep(5)
        tg.cancel_scope.cancel()

    values = [e.value for e in recorded_entries]
    assert values == [10, 30, 50]


@pytest.mark.trio
async def test_worker_attr_extraction(recorded_entries, autojump_clock):  # noqa:ARG001
    """Worker extracts nested attributes."""
    entry = _make_entry(attr=("nested", "val"))
    backend = MagicMock()
    backend.put = AsyncMock()
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx([(0, {"nested": {"val": 42}})]))

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_entry, link, entry, backend, P("test"))
        await anyio.sleep(1)
        tg.cancel_scope.cancel()

    assert recorded_entries[0].value == 42
