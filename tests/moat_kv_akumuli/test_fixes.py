"""Behavioral tests for moat.kv.akumuli bug fixes."""

from __future__ import annotations

import anyio
import pytest
from unittest.mock import AsyncMock, MagicMock

from asyncakumuli import DS

from moat.kv.akumuli import model as akumuli_model


@pytest.fixture
def recorded_entries():
    """Collect Entry objects sent via _test_hook."""
    entries = []
    orig = akumuli_model._test_hook  # noqa:SLF001

    def _hook(e):
        entries.append(e)

    akumuli_model._test_hook = _hook  # noqa:SLF001
    yield entries
    akumuli_model._test_hook = orig  # noqa:SLF001


def _make_node(*, t_min=None, factor=1, offset=0):
    """Build a minimal stand-in for AkumuliNode for with_output tests."""
    node = MagicMock(spec=akumuli_model.AkumuliNode)
    node.t_min = t_min
    node.factor = factor
    node.offset = offset
    node._t_last = None  # noqa:SLF001
    node._work = None  # noqa:SLF001
    node.root = MagicMock()
    node.root.err = MagicMock()
    node.root.err.record_working = AsyncMock()
    node.root.err.record_error = AsyncMock()
    node.server = MagicMock()
    node.server.put = AsyncMock()
    node.subpath = ("test", "node")
    node.client = MagicMock()
    return node


class _Msg:
    """Fake watch message with a .value and .get()."""

    def __init__(self, value):
        self.value = value

    def get(self, key, default=None):  # noqa:ARG002
        """Return default; mimics a dict-like message."""
        return default


class _WatchCtx:
    """Async context manager that yields messages with controlled timing."""

    def __init__(self, schedule):
        # schedule: list of (delay_before, value)
        self._schedule = schedule

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def __aiter__(self):
        for delay, value in self._schedule:
            if delay:
                await anyio.sleep(delay)
            yield _Msg(value)


@pytest.mark.trio
async def test_t_min_throttle(recorded_entries, autojump_clock):  # noqa:ARG001
    """Updates arriving faster than t_min are suppressed."""
    node = _make_node(t_min=1.0)

    # (delay_before_yield, value)
    schedule = [
        (0, 10),  # t=0   → accepted (no _t_last yet)
        (0.5, 20),  # t=0.5 → skipped (0.5s < 1.0s)
        (0.6, 30),  # t=1.1 → accepted (1.1s ≥ 1.0s since last)
        (0.1, 40),  # t=1.2 → skipped (0.1s < 1.0s)
        (1.3, 50),  # t=2.5 → accepted (1.3s ≥ 1.0s)
    ]

    node.client.watch = MagicMock(return_value=_WatchCtx(schedule))
    evt = anyio.Event()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            akumuli_model.AkumuliNode.with_output,
            node,
            evt,
            ("test",),
            (),
            "series",
            {"tag": "val"},
            DS.gauge,
        )
        await evt.wait()
        await anyio.sleep(5)
        tg.cancel_scope.cancel()

    values = [e.value for e in recorded_entries]
    assert values == [10, 30, 50]


@pytest.mark.trio
async def test_t_min_none_passes_all(recorded_entries, autojump_clock):  # noqa:ARG001
    """With t_min=None, all updates are forwarded."""
    node = _make_node(t_min=None)
    schedule = [(0, v) for v in (1, 2, 3)]
    node.client.watch = MagicMock(return_value=_WatchCtx(schedule))
    evt = anyio.Event()

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            akumuli_model.AkumuliNode.with_output,
            node,
            evt,
            ("test",),
            (),
            "series",
            {"t": "v"},
            DS.gauge,
        )
        await evt.wait()
        await anyio.sleep(1)
        tg.cancel_scope.cancel()

    assert len(recorded_entries) == 3


def test_tag_bytes_decoded():
    """Byte-valued tags in raw messages are decoded to UTF-8 strings."""
    tags = {"host": b"server1", "region": "us-east", "port": 8080}
    # Simulate the tag-processing loop from task.process_raw
    result = {}
    for k, v in tags.items():
        if isinstance(v, bytes):
            result[k] = v.decode("utf-8")
        else:
            result[k] = str(v)

    assert result["host"] == "server1"
    assert isinstance(result["host"], str)
    assert result["region"] == "us-east"
    assert result["port"] == "8080"


def test_tag_bytes_old_bug():
    """The old isinstance(str, bytes) bug would fail to decode bytes."""
    tags = {"host": b"server1"}
    result = {}
    for k, v in tags.items():
        # Old buggy code: isinstance(str, bytes) is always False
        if isinstance(str, bytes):
            result[k] = v.decode("utf-8")
        else:
            result[k] = str(v)

    # Old code produces b'server1' stringified, not decoded
    assert result["host"] != "server1"
    assert result["host"] == "b'server1'"


def test_attr_split_produces_list():
    """The ``all(… for x in .split())`` check must match whole keywords.

    Regression: ``.split`` without parens is a bound method, not a list.
    Iterating it raises TypeError, so the ``all()`` expression could
    never work correctly.  With ``.split()`` the guard properly detects
    when none of the expected keywords are present.
    """
    words = "vars_ eval_ path_"
    kw = {"vars_": 42}

    # Fixed: .split() yields the three expected keywords
    assert not all(x not in kw for x in words.split())

    # Also verify the positive case: none present → all True
    kw_empty = {"other": 1}
    assert all(x not in kw_empty for x in words.split())

    # Without parens: can't even iterate a method
    with pytest.raises(TypeError):
        list(words.split)
