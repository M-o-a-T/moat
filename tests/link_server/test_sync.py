from __future__ import annotations

import anyio
import pytest
import time

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.util import P, PathLongener
from moat.lib.cmd import StreamError
from moat.link.client import BasicLink


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


async def data(s):
    await s("a.b.e", 10)
    await s("a.b.f", 11)
    await s("a.b.g.h", 12)
    await s("a.b.g.o", 121)
    await s("a.b.i", 13)
    await s("a.b.j", 14)
    await s("a.c", 15)
    await s("a.c.d", 16)
    await s("a.b.d", 17)


async def fetch(c,p):
    p=P(p)
    nn = Node()
    pl = PathLongener()
    async with c.stream_r(P("d.walk"),p) as msgs:
        try:
            it = aiter(msgs)
        except StreamError as exc:
            try:
                if exc.args[0][0] == "KeyError":
                    return nn  # empty
            except Exception:
                pass
            raise exc from None

        async for pr,p,d,*m in it:
            p=pl.long(pr,p)
            nn.set(p,d,MsgMeta.restore(m))
        return nn

@pytest.mark.anyio
async def test_lsy_from_server(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        n = Node()
        async def s(p,v):
            p=P(p)
            await c1.cmd(P("d.set"),p,v)
            n.set(p,v,MsgMeta(origin="Test"))
        await data(s)

        srv2 = await sf.server()
        async with BasicLink(cfg, "c_test", c1._last_link.data) as c2:
            nn = await fetch(c2,"a")

            assert n.get(P("a")) == nn


@pytest.mark.anyio
async def test_lsy_from_file(cfg, tmp_path):
    async with Scaffold(cfg, use_servers=True, tempdir=tmp_path) as sf:
        (sf.tempdir/"data").mkdir()

        srv1 = await sf.server(init={"Hello": "there!", "test": 123})
        c1 = await sf.client()
        n = Node()
        async def s(p,v):
            p=P(p)
            await c1.cmd(P("d.set"),p,v)
            n.set(p,v,MsgMeta(origin="Test"))
        await data(s)
        await srv1[0].stop()

    async with Scaffold(cfg, use_servers=True, tempdir=tmp_path) as sf:
        srv2 = await sf.server()
        c2 = await sf.client()
        nn = await fetch(c2,"a")

        assert n.get(P("a")) == nn


