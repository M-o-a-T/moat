"""Tests for moat.link.cmd.data dump/load helpers."""

from __future__ import annotations

import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.cmd import data as data_cmd
from moat.link.cmd.data import _dump_data, _load_data
from moat.link.meta import MsgMeta

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


class _ReaderCtx:
    data = []

    def __init__(self, path, codec):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        self._it = iter(type(self).data)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class _DirectSetter:
    def __init__(self):
        self.calls = []

    async def set(self, path, value, meta, **kw):
        self.calls.append((path, value, meta, kw))


class _Conn:
    def __init__(self):
        self.watch_items = []
        self.set_calls = []
        self.get_map = {}
        self.d = _DirectSetter()

    def d_watch(self, *a, **kw):  # noqa: ARG002
        return _WatchCtx(self.watch_items)

    async def d_set(self, path, value, meta=None):
        self.set_calls.append((path, value, meta))

    async def d_get(self, path, meta=False):
        path = str(path)
        if path not in self.get_map:
            raise KeyError(path)
        value, msg_meta = self.get_map[path]
        if not meta:
            return value
        return value, msg_meta


async def test_dump_removes_human_timestamp():
    """`dump` emits path/data/meta without `_timestamp` helpers."""

    conn = _Conn()
    nested = MsgMeta(origin="inner", timestamp=2.0, x=1)
    meta = MsgMeta(origin="outer", timestamp=3.0, gw=nested.repr(), mm=nested)
    conn.watch_items = [(P("a.b"), {"v": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    await _dump_data(obj)

    out = obj.stdout.getvalue()
    assert "_timestamp" not in out
    assert "origin: outer" in out
    assert "origin: inner" in out
    assert "timestamp: 3.0" in out
    assert "---" in out


async def test_load_respects_timestamps(monkeypatch):
    """`load` skips entries that are not newer unless forced."""

    monkeypatch.setattr(data_cmd, "MsgReader", _ReaderCtx)
    _ReaderCtx.data = [
        [P("a"), 1, {"origin": "src", "timestamp": 10.0}],
        [P("b"), 2, {"origin": "src", "timestamp": 5.0}],
        [P("c"), 3, {"origin": "src", "timestamp": 8.0}],
    ]

    conn = _Conn()
    conn.get_map[str(P("root.a"))] = (99, MsgMeta(origin="old", timestamp=9.0))
    conn.get_map[str(P("root.b"))] = (99, MsgMeta(origin="old", timestamp=7.0))
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    await _load_data(obj, "-", force=False)

    assert [str(p) for p, _v, _m in conn.set_calls] == ["root.a", "root.c"]
    assert conn.d.calls == []


async def test_load_force_overwrites():
    """`load --force` writes through `d.set(..., f=True)`."""

    _ReaderCtx.data = [[P("a"), 1, {"origin": "src", "timestamp": 1.0}]]

    conn = _Conn()
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    # Replace MsgReader here to avoid fixture requirements in this test.
    orig = data_cmd.MsgReader
    data_cmd.MsgReader = _ReaderCtx
    try:
        await _load_data(obj, "-", force=True)
    finally:
        data_cmd.MsgReader = orig

    assert conn.set_calls == []
    assert len(conn.d.calls) == 1
    p, v, m, kw = conn.d.calls[0]
    assert str(p) == "root.a"
    assert v == 1
    assert m.origin == "src"
    assert m.timestamp == 1.0
    assert kw == {"f": True}
