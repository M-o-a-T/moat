"""Tests for moat.link.schema."""

from __future__ import annotations

import anyio
import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.schema import _main as schema_cmd

pytestmark = pytest.mark.anyio


class _WatchCtx:
    def __init__(self, items, node=None):
        self._items = list(items)
        self._node = node

    async def __aenter__(self):
        async def _it():
            for item in self._items:
                yield item

        return _it()

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @property
    def node(self):
        return _NodeCtx(self._node)


class _NodeRes:
    def __init__(self, data):
        self.data = data


class _SchemaNode:
    def __init__(self, conn):
        self._conn = conn

    def search(self, path):
        if not self._conn.has_schema:
            raise KeyError(path)
        return _NodeRes({"type": "integer"})


class _NodeCtx:
    def __init__(self, node):
        self._node = node

    async def __aenter__(self):
        return self._node

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
        if path == P("schema"):
            return _WatchCtx([], node=_SchemaNode(self))
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


async def test_schema_monitor_queue_drops_when_busy(monkeypatch):
    """`schema monitor` drops excess messages instead of backlogging."""

    conn = _Conn()
    orig = schema_cmd._schema_error  # noqa: SLF001

    async def _slow_schema_error(*a, **k):
        await anyio.sleep(0.005)
        return await orig(*a, **k)

    monkeypatch.setattr(schema_cmd, "_schema_error", _slow_schema_error)
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


@pytest.mark.anyio
async def test_schema_monitor_e2e_writes_error(cfg):
    """`schema monitor` writes an error in a real client/server setup."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as watcher,
    ):
        await writer.d_set(P("schema.state.live"), {"type": "integer"}, verify=False)
        await writer.i_sync()
        await writer.d_set(P("state.live"), "bad", verify=False)
        await writer.i_sync()

        obj = attrdict(conn=watcher, stdout=StringIO())
        async with (
            sf.do_watch(P("error.schema.state"), subtree=True, n=1) as evt,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(schema_cmd.monitor.callback.__wrapped__, obj, P("state"), 0.0, False)
            await anyio.sleep(0.2)
            tg.cancel_scope.cancel()

        res = await evt.get()
        assert len(res) == 1
        p, d = res[0]
        assert p == P("live")
        assert d["data_path"] == P("state.live")
        assert d["data"] == "bad"
        assert "integer" in d["detail"]
