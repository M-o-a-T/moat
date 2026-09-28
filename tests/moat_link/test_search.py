"""
d.search against a real server.
"""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_d_search_dict(cfg):
    "d_search returns dict values (e.g. schemas); missing entries raise KeyError"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="INIT")
        c = await sf.client()
        await c.d_set(P("test.search.a"), {"type": "number"}, retain=True, verify=False)
        await c.i_sync()
        assert await c.d_search(P("test.search.a")) == {"type": "number"}
        data, meta = await c.d_search(P("test.search.a"), meta=True)
        assert data == {"type": "number"}
        assert meta.origin
        with pytest.raises(KeyError):
            await c.d_search(P("test.search.nothing.here"))


async def test_d_search_no_stream(cfg):
    "d.search is not a streaming command"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="INIT")
        c = await sf.client()

        async def stream() -> None:
            async with c.d.search(P("test.search.a")).stream_in() as st:
                async for _ in st:
                    pass

        with pytest.raises(Exception, match="does not stream"):
            await stream()
