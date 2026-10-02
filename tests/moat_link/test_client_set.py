"""
LinkSender.set / .get, as used by code snippets (``_link``).
"""

from __future__ import annotations

import pytest

from moat.util import NotGiven
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.meta import MsgMeta

pytestmark = pytest.mark.anyio


async def test_set_get(cfg):
    "set/get round trip; d_set keywords are passed through"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="INIT")
        c = await sf.client()
        assert await c.set(P("test.sg.a"), 1, meta=MsgMeta(origin="snip")) is True
        await c.i_sync()
        assert await c.get(P("test.sg.a")) == 1
        data, meta = await c.get(P("test.sg.a"), meta=True)
        assert data == 1
        assert meta.origin == "snip"

        old = await c.set(P("test.sg.a"), 2, with_prev=True)
        assert old[0] == 1
        await c.i_sync()
        assert await c.get(P("test.sg.a")) == 2

        with pytest.raises(KeyError):
            await c.get(P("test.sg.nothing"))


async def test_set_idem(cfg):
    "idem=True skips writing an unchanged value"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="INIT")
        c = await sf.client()
        p = P("test.sg.idem")

        writes = []
        d_set = c.d_set

        async def _d_set(path, data, **kw):
            writes.append(data)
            return await d_set(path, data, **kw)

        c.d_set = _d_set

        assert await c.set(p, 5, idem=True) is True
        await c.i_sync()
        assert writes == [5]

        assert await c.set(p, 5, idem=True) is False
        old = await c.set(p, 5, idem=True, with_prev=True)
        assert old[0] == 5
        assert writes == [5]

        assert await c.set(p, 5) is True
        assert writes == [5, 5]

        assert await c.set(p, 6, idem=True) is True
        await c.i_sync()
        assert await c.get(p) == 6
        assert writes == [5, 5, 6]

        # deleting something that isn't there
        assert await c.set(P("test.sg.nothing"), NotGiven, idem=True) is False


async def test_call_admin_set_passes_keywords():
    "_self.set forwards keywords to _link.set"
    from moat.link.job.runner import CallAdmin  # noqa: PLC0415

    seen = []

    class _Link:
        async def set(self, path, value, **kw):
            seen.append((path, value, kw))
            return False

    adm = object.__new__(CallAdmin)
    adm._link = _Link()  # noqa: SLF001

    class _Entry:
        path = P("job.test")

    adm._entry = _Entry()  # noqa: SLF001
    assert await adm.set(("test", "x"), 3, idem=True, retain=False) is False
    # … and names the job as the data's source
    meta = {"src": P("job.test")}
    assert seen == [(P("test.x"), 3, {"idem": True, "retain": False, "meta": meta})]
