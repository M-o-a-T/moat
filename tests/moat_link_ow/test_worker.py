"""Worker-level tests for moat.link.ow.

Exercises :func:`moat.link.ow.worker.forward_read` (device→Link) and
:func:`moat.link.ow.worker.run_out` (Link→device) with faked Link and
asyncowfs device objects.
"""

from __future__ import annotations

import anyio
import pytest
from unittest.mock import AsyncMock, MagicMock

from moat.util import NotGiven
from moat.lib.path import P
from moat.link.meta import MsgMeta
from moat.link.ow import worker as ow_worker
from moat.link.ow.model import OwAttr


def _make_entry(**data) -> OwAttr:
    """Build an OwAttr with given config overlay."""
    defaults: dict = {}
    defaults.update(data)
    e = OwAttr()
    e.set_((), defaults, MsgMeta(origin="t", timestamp=1))
    return e


class _WatchCtx:
    """Fake d_watch async context manager / iterator.

    Items are 2-tuples ``(delay, val)``.  Yields the value directly.
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


def _link_with_watch(values):
    """Build a fake LinkSender with a ``d_watch``."""
    link = MagicMock()
    link.d_watch = MagicMock(return_value=_WatchCtx(values))
    return link


@pytest.mark.trio
async def test_forward_read_plain(autojump_clock):  # noqa:ARG001
    """Without ``dest_attr`` the polled value replaces ``dest``."""
    entry = _make_entry(dest=("data", "temp"))
    link = MagicMock()
    link.d_get = AsyncMock(side_effect=KeyError)
    link.d_set = AsyncMock()

    await ow_worker.forward_read(link, entry, 12.5)

    link.d_set.assert_awaited_once_with(P("data.temp"), 12.5)


@pytest.mark.trio
async def test_forward_read_merge(autojump_clock):  # noqa:ARG001
    """With ``dest_attr`` the polled value is merged into ``dest``'s dict."""
    entry = _make_entry(dest=("data", "this"), dest_attr=("baz", 2))
    link = MagicMock()

    async def _get(_path, meta=False):  # noqa: ARG001
        return {"this": "is", "baz": {3: 33}}

    link.d_get = AsyncMock(side_effect=_get)
    link.d_set = AsyncMock()

    await ow_worker.forward_read(link, entry, 22)

    args = link.d_set.await_args
    assert args.args[0] == P("data.this")
    merged = args.args[1]
    assert merged["this"] == "is"
    assert merged["baz"][2] == 22
    assert merged["baz"][3] == 33


@pytest.mark.trio
async def test_forward_read_merge_into_empty(autojump_clock):  # noqa:ARG001
    """A missing ``dest`` dict is created fresh before merging."""
    entry = _make_entry(dest=("data", "this"), dest_attr=("baz", 2))
    link = MagicMock()
    link.d_get = AsyncMock(side_effect=KeyError)
    link.d_set = AsyncMock()

    await ow_worker.forward_read(link, entry, 22)

    args = link.d_set.await_args
    merged = args.args[1]
    assert merged["baz"][2] == 22


@pytest.mark.trio
async def test_forward_read_no_dest(autojump_clock):  # noqa:ARG001
    """A write-only entry is a no-op for the read direction."""
    entry = _make_entry(src=("cmd", "x"))
    link = MagicMock()
    link.d_set = AsyncMock()

    await ow_worker.forward_read(link, entry, 42)

    link.d_set.assert_not_awaited()


@pytest.mark.trio
async def test_run_out_plain(monkeypatch, autojump_clock):  # noqa:ARG001
    """Basic write mode forwards watched values to the device."""
    entry = _make_entry(src=("cmd", "low"))
    link = _link_with_watch([(0, 11), (0, 0)])
    dev = MagicMock()
    dev.set = AsyncMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ow_worker.run_out, link, dev, entry, P("templow"), P("g1.16.345678.templow"))
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert dev.set.await_count == 2
    dev.set.assert_any_call("templow", value=11)
    dev.set.assert_any_call("templow", value=0)


@pytest.mark.trio
async def test_run_out_src_attr(monkeypatch, autojump_clock):  # noqa:ARG001
    """``src_attr`` extracts a nested field before writing to the device."""
    entry = _make_entry(src=("cmd", "x"), src_attr=("bar", 1))
    link = _link_with_watch([(0, {"bar": {0: 99, 1: 13}})])
    dev = MagicMock()
    dev.set = AsyncMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ow_worker.run_out, link, dev, entry, P("foo.bar"), P("g1.16.345678.foo.bar"))
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    dev.set.assert_awaited_once_with("foo", "bar", value=13)


@pytest.mark.trio
async def test_run_out_skip_notgiven(monkeypatch, autojump_clock):  # noqa:ARG001
    """``NotGiven`` values from the watcher are skipped."""
    entry = _make_entry(src=("cmd", "x"))
    link = _link_with_watch([(0, NotGiven), (0, True)])
    dev = MagicMock()
    dev.set = AsyncMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ow_worker.run_out, link, dev, entry, P("templow"), P("g1.16.345678.templow"))
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    dev.set.assert_awaited_once_with("templow", value=True)


@pytest.mark.trio
async def test_run_out_src_attr_missing(monkeypatch, autojump_clock):  # noqa:ARG001
    """A missing ``src_attr`` field is logged and the write is skipped."""
    entry = _make_entry(src=("cmd", "x"), src_attr=("bar", 1))
    link = _link_with_watch([(0, {"bar": {0: 99}})])  # no index 1
    dev = MagicMock()
    dev.set = AsyncMock()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ow_worker.run_out, link, dev, entry, P("foo.bar"), P("g1.16.345678.foo.bar"))
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    dev.set.assert_not_awaited()
