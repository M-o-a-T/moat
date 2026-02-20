"""Tests for moat.link.cmd.data dump/load helpers."""

from __future__ import annotations

import anyio
import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.cmd import data as data_cmd
from moat.link.cmd.data import _dump_data, _load_data
from moat.link.meta import MsgMeta

pytestmark = pytest.mark.anyio


class _WatchCtx:
    def __init__(self, items, *, meta: bool):
        self._items = list(items)
        self._meta = meta

    async def __aenter__(self):
        async def _it():
            for item in self._items:
                if self._meta:
                    yield item
                elif isinstance(item, tuple) and len(item) == 3:
                    yield item[:2]
                else:
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
        self.res = []

    async def set(self, path, value, meta, **kw):
        self.calls.append((path, value, meta, kw))
        if self.res:
            return self.res.pop(0)
        return True


class _Conn:
    def __init__(self):
        self.watch_items = []
        self.d = _DirectSetter()
        self.name = "conn"

    def d_watch(self, *a, **kw):  # noqa: ARG002
        return _WatchCtx(self.watch_items, meta=kw.get("meta", False))


_MISSING = object()


class _EditConn:
    def __init__(self, data=_MISSING, template=_MISSING):
        self._data = data
        self._template = template
        self.get_calls = []
        self.search_calls = []
        self.set_calls = []

    async def d_get(self, path):
        self.get_calls.append(path)
        if self._data is _MISSING:
            raise KeyError(path)
        return self._data

    async def d_search(self, path):
        self.search_calls.append(path)
        if self._template is _MISSING:
            raise KeyError(path)
        return self._template

    async def d_set(self, path, data, meta=None):
        self.set_calls.append((path, data, meta))
        return True


async def test_dump_removes_human_timestamp():
    """`dump` emits path/data/meta without `_timestamp` helpers."""

    conn = _Conn()
    nested = MsgMeta(origin="inner", timestamp=2.0, x=1)
    meta = MsgMeta(origin="outer", timestamp=3.0, gw=nested.dump(), mm=nested.dump())
    conn.watch_items = [(P("a.b"), {"v": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO(), meta=True)

    await _dump_data(obj)

    out = obj.stdout.getvalue()
    assert "_timestamp" not in out
    assert "\n- - outer\n" not in out
    assert "\n- outer\n" in out
    assert "outer" in out
    assert "inner" in out
    assert "3.0" in out
    assert "---" in out


async def test_dump_dict_inlines_simple_mapping():
    """`dump --dict` emits `_path` / `_meta` plus direct mapping values."""

    conn = _Conn()
    meta = MsgMeta(origin="outer", timestamp=3.0)
    conn.watch_items = [(P("a.b"), {"v": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO(), meta=True)

    await _dump_data(obj, as_dict=True)

    out = obj.stdout.getvalue()
    assert "_path: a.b" in out
    assert "_meta:" in out
    assert "_value:" not in out
    assert "\nv: 1\n" in out
    assert "!P" not in out


async def test_dump_dict_wraps_reserved_values():
    """`dump --dict` stores reserved-key mappings under `_value`."""

    conn = _Conn()
    meta = MsgMeta(origin="outer", timestamp=3.0)
    conn.watch_items = [(P("a.b"), {"_foo": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO(), meta=True)

    await _dump_data(obj, as_dict=True)

    out = obj.stdout.getvalue()
    assert "_value:" in out
    assert "_foo: 1" in out


async def test_dump_without_meta_emits_two_elements():
    """`dump` omits metadata unless `-m/--meta` is set."""

    conn = _Conn()
    meta = MsgMeta(origin="outer", timestamp=3.0)
    conn.watch_items = [(P("a.b"), {"v": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO(), meta=False)

    await _dump_data(obj)

    out = obj.stdout.getvalue()
    assert out.startswith("- !P a.b\n- v: 1\n")
    assert "outer" not in out
    assert "_timestamp" not in out


async def test_dump_dict_without_meta_omits_meta_key():
    """`dump --dict` omits `_meta` unless `-m/--meta` is set."""

    conn = _Conn()
    meta = MsgMeta(origin="outer", timestamp=3.0)
    conn.watch_items = [(P("a.b"), {"v": 1}, meta)]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO(), meta=False)

    await _dump_data(obj, as_dict=True)

    out = obj.stdout.getvalue()
    assert "_path: a.b" in out
    assert "_meta:" not in out
    assert "\nv: 1\n" in out


async def test_load_respects_timestamps(monkeypatch):
    """`load` skips entries that are not newer unless forced."""

    monkeypatch.setattr(data_cmd, "MsgReader", _ReaderCtx)
    _ReaderCtx.data = [
        [P("a"), 1, "src", 10.0],
        [P("b"), 2, "src", 5.0],
        [P("c"), 3, "src", 8.0],
    ]

    conn = _Conn()
    conn.d.res = [True, False, True]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    await _load_data(obj, "-", force=False)

    assert [str(p) for p, _v, _m, _kw in conn.d.calls] == ["root.a", "root.b", "root.c"]


async def test_load_force_retries_with_start_timestamp(monkeypatch):
    """`load --force` retries stale data with current-time metadata."""

    monkeypatch.setattr(data_cmd, "MsgReader", _ReaderCtx)
    monkeypatch.setattr(data_cmd.time, "time", lambda: 9999.25)
    _ReaderCtx.data = [[P("a"), 1, "src", 1.0]]

    conn = _Conn()
    conn.d.res = [False, True]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    await _load_data(obj, "-", force=True)

    assert len(conn.d.calls) == 2
    p1, v1, m1, kw1 = conn.d.calls[0]
    p2, v2, m2, kw2 = conn.d.calls[1]
    assert str(p1) == "root.a"
    assert str(p2) == "root.a"
    assert v1 == v2 == 1
    assert m1.timestamp == 1.0
    assert m2.timestamp == 9999.25
    assert kw1 == kw2 == {}


async def test_load_force_overwrites():
    """`load --force` does not retry when equal data is reported."""

    _ReaderCtx.data = [[P("a"), 1, "src", 1.0]]

    conn = _Conn()
    conn.d.res = [None]
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    # Replace MsgReader here to avoid fixture requirements in this test.
    orig = data_cmd.MsgReader
    data_cmd.MsgReader = _ReaderCtx
    try:
        await _load_data(obj, "-", force=True)
    finally:
        data_cmd.MsgReader = orig

    assert len(conn.d.calls) == 1
    p, v, m, kw = conn.d.calls[0]
    assert str(p) == "root.a"
    assert v == 1
    assert m.origin == "src"
    assert m.timestamp == 1.0
    assert kw == {}


async def test_load_dict_format_and_optional_meta(monkeypatch):
    """`load` auto-detects dict docs and accepts missing `_meta`."""

    monkeypatch.setattr(data_cmd, "MsgReader", _ReaderCtx)
    _ReaderCtx.data = [
        {"_path": "a", "_meta": ["src", 1.0], "x": 1},
        {"_path": "b", "_value": 2},
        {"_path": "c", "_meta": {"origin": "m", "timestamp": 3.0, "_drop": 9}, "y": 4},
        {"path": P("d"), "value": 5, "meta": ["z", 6.0]},
        [P("e"), 7],
    ]

    conn = _Conn()
    obj = attrdict(conn=conn, path=P("root"), stdout=StringIO())

    await _load_data(obj, "-", force=False)

    assert [str(p) for p, _v, _m, _kw in conn.d.calls] == [
        "root.a",
        "root.b",
        "root.c",
        "root.d",
        "root.e",
    ]
    _p, v1, m1, _kw = conn.d.calls[0]
    _p, v2, m2, _kw = conn.d.calls[1]
    _p, v3, m3, _kw = conn.d.calls[2]
    _p, v4, m4, _kw = conn.d.calls[3]
    _p, v5, m5, _kw = conn.d.calls[4]
    assert v1 == {"x": 1}
    assert m1.origin == "src"
    assert m1.timestamp == 1.0
    assert v2 == 2
    assert m2 is None
    assert v3 == {"y": 4}
    assert m3.origin == "m"
    assert m3.timestamp == 3.0
    assert "_drop" not in m3.kw
    assert v4 == 5
    assert m4.origin == "z"
    assert m4.timestamp == 6.0
    assert v5 == 7
    assert m5 is None


async def test_edit_uses_template_and_skips_unchanged(monkeypatch):
    """`edit` uses template fallback and does not write unchanged content."""

    async def _noop_run(*_a, **_kw):
        return None

    monkeypatch.setattr(data_cmd, "run", _noop_run)
    conn = _EditConn(data=_MISSING, template={"x": 1})
    obj = attrdict(conn=conn, path=P("foo.bar"), meta=False, stdout=StringIO())

    await data_cmd.edit.callback.__wrapped__(obj, yes=True, editor="dummy")

    assert [str(p) for p in conn.get_calls] == ["foo.bar"]
    assert [str(p) for p in conn.search_calls] == ["template.foo.bar"]
    assert conn.set_calls == []


async def test_edit_writes_changed_template(monkeypatch):
    """`edit` writes when template content gets modified."""

    async def _edit_run(_editor, path, **_kw):
        async with await anyio.open_file(path, "w", encoding="utf-8") as f:
            await f.write("x: 2\n")

    monkeypatch.setattr(data_cmd, "run", _edit_run)
    conn = _EditConn(data=_MISSING, template={"x": 1})
    obj = attrdict(conn=conn, path=P("foo.bar"), meta=False, stdout=StringIO())

    await data_cmd.edit.callback.__wrapped__(obj, yes=True, editor="dummy")

    assert [str(p) for p in conn.search_calls] == ["template.foo.bar"]
    assert len(conn.set_calls) == 1
    p, d, _m = conn.set_calls[0]
    assert str(p) == "foo.bar"
    assert d == {"x": 2}
