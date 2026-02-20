"""Tests for moat.link.cmd.schema."""

from __future__ import annotations

import pytest
from io import StringIO

from moat.util import attrdict
from moat.lib.path import P
from moat.link.cmd import schema as schema_cmd

pytestmark = pytest.mark.anyio


class _Conn:
    def __init__(self):
        self.calls = []

    async def d_search(self, path):
        self.calls.append(path)
        return {"type": "integer"}


async def test_schema_get_uses_search_path():
    """`schema get` reads from `schema.*` via d_search."""

    conn = _Conn()
    obj = attrdict(conn=conn, stdout=StringIO())

    await schema_cmd.get.callback.__wrapped__(obj, P("foo.bar"))

    assert [str(p) for p in conn.calls] == ["schema.foo.bar"]
    assert "type: integer" in obj.stdout.getvalue()
