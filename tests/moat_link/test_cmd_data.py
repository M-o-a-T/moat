"""Tests for moat.link.cmd.data dump/load helpers."""

from __future__ import annotations

import pytest
from io import StringIO

import asyncclick as click

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.cmd import data as data_cmd
from moat.link.cmd.data import _dump_data, _import_data, _load_data
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
    assert "_path: root.a.b" in out
    assert "_meta:" in out
    assert "_value:" not in out
    assert "\nv: 1\n" in out
    assert "!P" not in out
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
    assert "_path: root.a.b" in out
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


async def test_data_cli_uses_selected_server(monkeypatch):
    """`moat link -s NAME data ...` forwards NAME to `Link(..., only=...)`."""

    calls = []

    class _Link:
        def __init__(self, cfg, *, common=False, only=None):
            calls.append((cfg, common, only))

    async def _with_async_resource(res):
        return res

    monkeypatch.setattr(data_cmd, "Link", _Link)
    ctx = attrdict(
        obj=attrdict(cfg=attrdict(link=attrdict()), link_name="foo", stdout=StringIO()),
        with_async_resource=_with_async_resource,
        invoked_subcommand="get",
    )

    await data_cmd.cli.callback.__wrapped__(ctx, P(":"), False)

    assert calls == [(ctx.obj.cfg.link, True, "foo")]


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

    async def _edit_text(_editor, text, *, suffix):  # noqa: ARG001
        return text

    monkeypatch.setattr(data_cmd, "edit_text", _edit_text)
    conn = _EditConn(data=_MISSING, template={"x": 1})
    obj = attrdict(conn=conn, path=P("foo.bar"), meta=False, stdout=StringIO())

    await data_cmd.edit.callback.__wrapped__(obj, yes=True, editor="dummy")

    assert [str(p) for p in conn.get_calls] == ["foo.bar"]
    assert [str(p) for p in conn.search_calls] == ["template.foo.bar"]
    assert conn.set_calls == []


async def test_edit_writes_changed_template(monkeypatch):
    """`edit` writes when template content gets modified."""

    async def _edit_text(_editor, _text, *, suffix):  # noqa: ARG001
        return "x: 2\n"

    monkeypatch.setattr(data_cmd, "edit_text", _edit_text)
    conn = _EditConn(data=_MISSING, template={"x": 1})
    obj = attrdict(conn=conn, path=P("foo.bar"), meta=False, stdout=StringIO())

    await data_cmd.edit.callback.__wrapped__(obj, yes=True, editor="dummy")

    assert [str(p) for p in conn.search_calls] == ["template.foo.bar"]
    assert len(conn.set_calls) == 1
    p, d, _m = conn.set_calls[0]
    assert str(p) == "foo.bar"
    assert d == {"x": 2}


class _ImportConn:
    """Minimal conn capturing :py:meth:`d_set` calls for import tests."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.name = "conn"

    async def d_set(self, path, data, meta=None):
        self.calls.append((path, data, meta))
        return True


async def test_import_legacy_list_format(tmp_path):
    """`import --legacy` ingests the YAML-list output of `kv data get -r`.

    Exercises path-string, tagged-Path and list-of-segments forms as
    well as plain ``str`` paths produced by some legacy dumps.
    """

    src = tmp_path / "dump.yaml"
    # mix of !P-tagged Path, string and list-form path keys
    src.write_text("- !P a.b: 42\n- !P a.c: hi\n- !P x:\n    nested: 1\n- p.q: 7\n- [k, l]: 9\n")

    conn = _ImportConn()
    obj = attrdict(conn=conn, path=P("root"))

    await _import_data(obj, str(src), as_dict=None)

    assert [(str(p), v) for p, v, _m in conn.calls] == [
        ("root.a.b", 42),
        ("root.a.c", "hi"),
        ("root.x", {"nested": 1}),
        ("root.p.q", 7),
        ("root.k.l", 9),
    ]


async def test_import_as_dict_format(tmp_path):
    """`import --as-dict KEY` walks the nested-dict output of `kv data get -r -d KEY`."""

    src = tmp_path / "dump.yaml"
    src.write_text(
        "a:\n  b:\n    _: 42\n  c:\n    _: hi\nx:\n  _:\n    nested: 1\n  sub:\n    _: 7\n"
        # stray non-dict entry with a non-marker key is silently skipped
        "z:\n  ignored: scalar\n"
    )

    conn = _ImportConn()
    obj = attrdict(conn=conn, path=P("root"))

    await _import_data(obj, str(src), as_dict="_")

    got = sorted((str(p), v) for p, v, _m in conn.calls)
    assert got == [
        ("root.a.b", 42),
        ("root.a.c", "hi"),
        ("root.x", {"nested": 1}),
        ("root.x.sub", 7),
    ]


async def test_import_rejects_wrong_shape(tmp_path):
    """`import --legacy` rejects a mapping at the top, and vice versa.

    Also rejects an unsupported path representation (e.g. a number).
    """

    src = tmp_path / "wrong.yaml"
    src.write_text("a:\n  _: 1\n")

    conn = _ImportConn()
    obj = attrdict(conn=conn, path=P("root"))

    with pytest.raises(click.UsageError, match="YAML list"):
        await _import_data(obj, str(src), as_dict=None)
    assert conn.calls == []

    src.write_text("- !P a: 1\n")
    with pytest.raises(click.UsageError, match="YAML mapping"):
        await _import_data(obj, str(src), as_dict="_")
    assert conn.calls == []

    # legacy with an unparseable path-key type → helpful error.
    src.write_text("- 42: 1\n")
    with pytest.raises(click.UsageError, match="as a path"):
        await _import_data(obj, str(src), as_dict=None)
    assert conn.calls == []


async def test_import_cli_requires_one_mode(tmp_path):
    """`import` errors when neither (or both) --legacy/--as-dict are given."""

    src = tmp_path / "x.yaml"
    src.write_text("- !P a: 1\n")
    conn = _ImportConn()
    obj = attrdict(conn=conn, path=P("root"))

    with pytest.raises(click.UsageError):
        await data_cmd.import_.callback.__wrapped__(
            obj, infile=str(src), legacy=False, as_dict=None
        )
    with pytest.raises(click.UsageError):
        await data_cmd.import_.callback.__wrapped__(obj, infile=str(src), legacy=True, as_dict="_")
    assert conn.calls == []

    # the happy path
    await data_cmd.import_.callback.__wrapped__(obj, infile=str(src), legacy=True, as_dict=None)
    assert [(str(p), v) for p, v, _m in conn.calls] == [("root.a", 1)]


async def test_import_e2e_against_real_link(cfg, tmp_path):
    """End-to-end check: imported entries land in the real Link store."""

    src = tmp_path / "dump.yaml"
    src.write_text("- !P one: 11\n- !P two.deep: hi\n")

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        obj = attrdict(conn=c, path=P("imp"))
        await _import_data(obj, str(src), as_dict=None)
        await c.i_sync()

        assert await c.d_get(P("imp.one")) == 11
        assert await c.d_get(P("imp.two.deep")) == "hi"
