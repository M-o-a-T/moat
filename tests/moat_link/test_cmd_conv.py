"""Tests for moat.link.cmd.conv helpers."""

from __future__ import annotations

import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.cmd.conv import (
    _conv_prefix,
    _do_add,
    _do_delete,
    _do_get,
    _do_list,
    _do_set,
    _ensure_absent,
    _ensure_exists,
)

pytestmark = pytest.mark.anyio


def _make_obj(client, *, meta: bool = False):
    return attrdict(
        conn=client,
        stdout=StringIO(),
        meta=meta,
        debug=False,
        cfg=attrdict(link=attrdict(conv=attrdict(prefix=P("conv")))),
    )


def test_conv_prefix_default():
    """``_conv_prefix`` falls back to ``conv`` if the config is missing."""
    obj = attrdict(cfg=attrdict(link=attrdict()))
    assert _conv_prefix(obj) == P("conv")


def test_conv_prefix_configured():
    """``_conv_prefix`` honors a custom config value."""
    obj = attrdict(cfg=attrdict(link=attrdict(conv=attrdict(prefix=P("foo.bar")))))
    assert _conv_prefix(obj) == P("foo.bar")


async def test_ensure_exists_and_absent(cfg):
    """``_ensure_exists``/``_ensure_absent`` map presence/absence to UsageError."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as client,
    ):
        import asyncclick as click  # noqa: PLC0415

        # absent path: _ensure_exists raises
        with pytest.raises(click.UsageError):
            await _ensure_exists(client, P("conv.nope"), "Entry")
        # absent path: _ensure_absent passes
        await _ensure_absent(client, P("conv.nope"), "Entry")

        await client.d_set(P("conv.live"), {"codec": P("x")})
        await client.i_sync()
        # present path: _ensure_exists passes
        await _ensure_exists(client, P("conv.live"), "Entry")
        # present path: _ensure_absent raises
        with pytest.raises(click.UsageError):
            await _ensure_absent(client, P("conv.live"), "Entry")


async def test_conv_lifecycle(cfg):
    """End-to-end: add, get, set, list, delete on a converter and a sub-entry."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as client,
    ):
        # add conv.A
        obj = _make_obj(client)
        obj.parent_path = None
        obj.path = P("conv.A")
        await _do_add(obj, P("default.codec"), require_parent=False)
        await client.i_sync()

        # get conv.A
        obj2 = _make_obj(client)
        obj2.path = P("conv.A")
        await _do_get(obj2)
        assert "default.codec" in obj2.stdout.getvalue()

        # set conv.A
        obj3 = _make_obj(client)
        obj3.path = P("conv.A")
        await _do_set(
            obj3,
            {
                "path_": ((P("codec"), P("changed.codec")),),
                "set_": (),
                "args_": (),
                "vars_": (),
                "eval_": (),
            },
        )
        await client.i_sync()
        val = await client.d_get(P("conv.A"))
        assert val["codec"] == P("changed.codec")

        # add a sub-entry: parent ok, target absent
        obj4 = _make_obj(client)
        obj4.parent_path = P("conv.A")
        obj4.path = P("conv.A.sub.x")
        await _do_add(obj4, P("float.bin"), require_parent=True)
        await client.i_sync()

        # list shows both entries
        obj5 = _make_obj(client)
        obj5.path = P("conv.A")
        await _do_list(obj5)
        out = obj5.stdout.getvalue()
        assert "conv.A : changed.codec" in out
        assert "conv.A.sub.x : float.bin" in out

        # non-recursive delete on sub.x leaves siblings alone
        obj6 = _make_obj(client)
        obj6.path = P("conv.A.sub.x")
        await _do_delete(obj6, recursive=False)
        await client.i_sync()
        with pytest.raises(KeyError):
            await client.d_get(P("conv.A.sub.x"))
        assert (await client.d_get(P("conv.A")))["codec"] == P("changed.codec")

        # recursive delete clears the whole subtree
        await client.d_set(P("conv.A.sub.x"), {"codec": P("y")})
        await client.i_sync()
        obj7 = _make_obj(client)
        obj7.path = P("conv.A")
        await _do_delete(obj7, recursive=True)
        await client.i_sync()
        with pytest.raises(KeyError):
            await client.d_get(P("conv.A"))
        with pytest.raises(KeyError):
            await client.d_get(P("conv.A.sub.x"))


async def test_conv_add_rejects_duplicates_and_missing_parents(cfg):
    """``add`` enforces target absence and (optionally) parent presence."""
    import asyncclick as click  # noqa: PLC0415

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as client,
    ):
        obj = _make_obj(client)
        obj.parent_path = None
        obj.path = P("conv.B")
        await _do_add(obj, P("c1"), require_parent=False)
        await client.i_sync()

        # second add fails — already exists
        obj2 = _make_obj(client)
        obj2.parent_path = None
        obj2.path = P("conv.B")
        with pytest.raises(click.UsageError):
            await _do_add(obj2, P("c2"), require_parent=False)

        # sub-add requires the parent to exist
        obj3 = _make_obj(client)
        obj3.parent_path = P("conv.NotThere")
        obj3.path = P("conv.NotThere.x")
        with pytest.raises(click.UsageError):
            await _do_add(obj3, P("c3"), require_parent=True)
