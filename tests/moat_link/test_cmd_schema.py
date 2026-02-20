"""Tests for moat.link.cmd.schema."""

from __future__ import annotations

import anyio
import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.cmd import schema as schema_cmd

pytestmark = pytest.mark.anyio


class _WatchCtx:
    def __init__(self, items):
        self._items = list(items)

    async def __aenter__(self):
        async def _it():
            for item in self._items:
                yield item

        return _it()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Conn:
    def __init__(self):
        self.calls = []
        self.watch_items = []
        self.watch_calls = []
        self.error_calls = []
        self.delay = 0.0
        self.has_schema = True

    async def d_search(self, path):
        self.calls.append(path)
        if self.delay:
            await anyio.sleep(self.delay)
        if not self.has_schema:
            raise KeyError(path)
        return {"type": "integer"}

    def d_watch(self, path, **kw):
        self.watch_calls.append((path, kw))
        return _WatchCtx(self.watch_items)

    async def e_info(self, path, text, **kw):
        self.error_calls.append((path, text, kw))


async def test_schema_get_uses_search_path():
    """`schema get` reads from `schema.*` via d_search."""

    conn = _Conn()
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.get.callback.__wrapped__(obj, P("foo.bar"))

    assert [str(p) for p in conn.calls] == ["schema.foo.bar"]
    assert "type: integer" in obj.stdout.getvalue()


async def test_schema_monitor_rate_limit():
    """`schema monitor` rate-limits created error records."""

    conn = _Conn()
    conn.watch_items = [(P("a"), "x"), (P("b"), "y"), (P("c"), 3), (P("d"), "z")]
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.monitor.callback.__wrapped__(obj, P("foo"), 60.0, False)

    assert len(conn.error_calls) == 1
    p, _txt, kw = conn.error_calls[0]
    assert str(p) == "schema.foo.a"
    assert str(kw["data_path"]) == "foo.a"


async def test_schema_monitor_queue_drops_when_busy():
    """`schema monitor` drops excess messages instead of backlogging."""

    conn = _Conn()
    conn.delay = 0.005
    conn.watch_items = [(P(str(n)), "x") for n in range(200)]
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.monitor.callback.__wrapped__(obj, P("foo"), 0.0, False)

    assert len(conn.error_calls) < len(conn.watch_items)


async def test_schema_check_reports_invalid_entries():
    """`schema check` emits one report per invalid stored message."""

    conn = _Conn()
    conn.watch_items = [(P("a"), 1), (P("b"), "x"), (P("c"), "y")]
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.check.callback.__wrapped__(obj, P("foo"), False)

    out = obj.stdout.getvalue()
    assert "foo.b" in out
    assert "foo.c" in out
    assert "foo.a" not in out


async def test_schema_check_ignores_missing_schema():
    """`schema check` ignores entries that have no schema."""

    conn = _Conn()
    conn.has_schema = False
    conn.watch_items = [(P("a"), "x")]
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.check.callback.__wrapped__(obj, P("foo"), False)

    assert obj.stdout.getvalue() == ""
