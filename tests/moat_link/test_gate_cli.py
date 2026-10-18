"""The ``moat link gate`` subcommands address entries below ``gate``."""

from __future__ import annotations

import io
import pytest

import asyncclick as click

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.gate._main import delete, set_


class _D:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    async def delete(self, path, **kw):
        self.calls.append((path, kw))
        return [None]


@pytest.mark.anyio
@pytest.mark.parametrize("recursive", [False, True])
async def test_delete_prefix(recursive: bool) -> None:
    "`moat link gate heat delete` deletes gate.heat, not heat"
    d = _D()
    obj = attrdict(conn=attrdict(d=d), path=P("kv.heat"), meta=False, stdout=io.StringIO())
    async with click.Context(delete, obj=obj) as ctx:
        await ctx.invoke(delete, before=None, recursive=recursive)
    assert d.calls == [(P("gate.kv.heat"), {"rec": True} if recursive else {})]


class _MissingD:
    "RPC stub: the requested entry does not exist."

    async def get(self, path):
        raise KeyError(path)


class _Conn:
    "Records ``d_set`` calls; ``d.get`` always raises ``KeyError``."

    def __init__(self) -> None:
        self.d = _MissingD()
        self.calls: list[tuple[object, object]] = []
        self.name = "test"

    async def d_set(self, path, data, meta=None):  # noqa: ARG002
        self.calls.append((path, data))


@pytest.mark.anyio
async def test_set_missing_entry_stores_attrs() -> None:
    "Setting a non-existent gate entry must store the attributes, not an empty datum"
    conn = _Conn()
    obj = attrdict(conn=conn, path=P("foo"), meta=False, stdout=io.StringIO())
    async with click.Context(set_, obj=obj) as ctx:
        await ctx.invoke(
            set_,
            src=P("a.b"),
            dst=P("c.d"),
            driver="link",
            set_=(),
            vars_=(),
            eval_=(),
            path_=(),
            proxy_=(),
            args_=(),
        )
    assert conn.calls == [
        (
            P("gate.foo"),
            {"driver": "link", "src": P("a.b"), "dst": P("c.d")},
        ),
    ]


@pytest.mark.anyio
async def test_gate_set_creates_entry_once(cfg) -> None:
    "End-to-end: 'moat link gate foo set' stores the full entry in one go"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        obj = attrdict(conn=c, path=P("foo"), meta=False, stdout=io.StringIO())
        async with click.Context(set_, obj=obj) as ctx:
            await ctx.invoke(
                set_,
                src=P("a.b"),
                dst=P("c.d"),
                driver="link",
                set_=(),
                vars_=(),
                eval_=(),
                path_=(),
                proxy_=(),
                args_=(),
            )
        await c.i_sync()

        val = await c.d_get(P("gate.foo"))
        assert val == {"driver": "link", "src": P("a.b"), "dst": P("c.d")}
