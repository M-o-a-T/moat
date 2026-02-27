"""Tests for ``moat.link.flow``."""

from __future__ import annotations

import anyio
import pytest
import time
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.flow import _main as flow_cmd

pytestmark = pytest.mark.anyio


class _Sleep:
    def __init__(self, delay: float):
        self.delay = delay


class _WatchCtx:
    def __init__(self, items):
        self._items = list(items)

    async def __aenter__(self):
        async def _it():
            for item in self._items:
                if isinstance(item, _Sleep):
                    await anyio.sleep(item.delay)
                    continue
                yield item

        return _it()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self):
        self.search_calls = []
        self.get_calls = []
        self.watch_calls = []
        self.error_calls = []
        self.ok_calls = []
        self.watch_items = []
        self.flows = {}
        self.copies = {}

    async def d_search(self, path):
        self.search_calls.append(path)
        try:
            return self.flows[str(path)]
        except KeyError:
            raise KeyError(path) from None

    async def d_get(self, path):
        self.get_calls.append(path)
        try:
            return self.copies[str(path)]
        except KeyError:
            raise KeyError(path) from None

    def d_watch(self, path, **kw):
        self.watch_calls.append((path, kw))
        return _WatchCtx(self.watch_items)

    async def e_info(self, path, text, **kw):
        self.error_calls.append((path, text, kw))

    async def e_ok(self, path, **kw):
        self.ok_calls.append((path, kw))


async def test_flow_get_uses_flow_path():
    """`flow get` reads from `flow.*` via d_search."""

    conn = _Conn()
    conn.flows["flow.foo.bar"] = {"_": {"max": 5}}
    obj = attrdict(conn=conn, stdout=StringIO())

    await flow_cmd.get.callback.__wrapped__(obj, P("foo.bar"))

    assert [str(p) for p in conn.search_calls] == ["flow.foo.bar"]
    assert "max: 5" in obj.stdout.getvalue()


async def test_flow_check_reports_violations(monkeypatch):
    """`flow check` reports limits, copied mismatch, missing values and stale data."""

    conn = _Conn()
    conn.flows["flow.foo.a"] = {
        "_": {"timeout": 5.0},
        "x": {"_": {"max": 10.0}},
        "y": {"_": {"required": True}},
        "z": {"_": {"copied": {"at": P("mirror.a"), "item": P("z")}}},
    }
    conn.copies["mirror.a"] = {"z": 2}
    conn.watch_items = [(P("a"), {"x": 12, "z": 1}, attrdict(timestamp=90.0))]
    obj = attrdict(conn=conn, stdout=StringIO())
    monkeypatch.setattr(flow_cmd.time, "time", lambda: 100.0)

    await flow_cmd.check.callback.__wrapped__(obj, P("foo"), False, False)

    out = obj.stdout.getvalue()
    assert "foo.a" in out
    assert "12 > 10" in out
    assert "Missing data" in out
    assert "Copied mismatch" in out
    assert "Stale data" in out


async def test_flow_check_ok_when_values_match(monkeypatch):
    """`flow check` stays quiet for a valid dataset."""

    conn = _Conn()
    conn.flows["flow.foo.a"] = {
        "_": {"timeout": 5.0},
        "x": {"_": {"max": 10.0}},
        "z": {"_": {"copied": {"at": P("mirror.a"), "item": P("z")}}},
    }
    conn.copies["mirror.a"] = {"z": 1}
    conn.watch_items = [(P("a"), {"x": 9, "z": 1}, attrdict(timestamp=99.0))]
    obj = attrdict(conn=conn, stdout=StringIO())
    monkeypatch.setattr(flow_cmd.time, "time", lambda: 100.0)

    await flow_cmd.check.callback.__wrapped__(obj, P("foo"), False, False)

    assert obj.stdout.getvalue() == ""


async def test_flow_monitor_reports_and_clears_timeout():
    """`flow monitor` reports stale data and clears the error after an update."""

    conn = _Conn()
    conn.flows["flow.foo.a"] = {"_": {"timeout": 0.02}}
    t0 = time.time()
    conn.watch_items = [
        (P("a"), 1, attrdict(timestamp=t0)),
        _Sleep(0.08),
        (P("a"), 2, attrdict(timestamp=t0 + 0.08)),
        _Sleep(0.01),
    ]
    obj = attrdict(conn=conn, stdout=StringIO())

    await flow_cmd.monitor.callback.__wrapped__(obj, P("foo"))

    assert any(text.startswith("No update for") for _p, text, _kw in conn.error_calls)
    assert any(str(p) == "flow.foo.a" for p, _kw in conn.ok_calls)
