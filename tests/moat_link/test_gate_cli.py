"""The ``moat link gate`` subcommands address entries below ``gate``."""

from __future__ import annotations

import io
import pytest

import asyncclick as click

from moat.util import attrdict
from moat.lib.path import P
from moat.link.gate._main import delete


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
