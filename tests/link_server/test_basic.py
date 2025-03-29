from __future__ import annotations

import anyio
import pytest
import time

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.util import P, PathLongener, NotGiven
from moat.lib.cmd import StreamError


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


@pytest.mark.anyio
async def test_ls_basic(cfg):
    evt = anyio.Event()
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)

        async def cl(exp, *, task_status):
            c = await sf.client()

            async with c.monitor(P(":R.test.here")) as mon:
                task_status.started()
                async for m in mon:
                    assert m.data == exp
                    assert m.meta.origin == "me!"
                    t = time.time()
                    assert t - 1 < m.meta.timestamp < t
                    evt.set()
                    break

        srv = await sf.server(init={"Hello": "there!", "test": 123})
        await sf.tg.start(cl, "Hello")

        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"], r
        a, b = r  # we can iterate the result to get at the data
        assert (a, b) == ("乓", "pling"), (a, b)

        om = MsgMeta(origin="me!")
        await c.send(P(":R.test.here"), "Hello", meta=om)
        with anyio.fail_after(1):
            await evt.wait()

        r, m = await c.cmd(P("d.get"), P("test.here"))
        assert r == "Hello"
        assert m.origin == "me!"

        r, m = await c.cmd(P("d.get"), P(":"))
        assert r["test"] == 123
        assert m.origin == "INIT"

        evt = anyio.Event()
        await sf.tg.start(cl, 999)
        om = MsgMeta(origin="me!")
        await c.cmd(P("d.set"), P("test.here"), 999, om)
        with anyio.fail_after(1):
            await evt.wait()


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


async def fetch(c, p):
    p = P(p)
    nn = Node()
    pl = PathLongener()
    async with c.stream_r(P("d.walk"), p) as msgs:
        try:
            it = aiter(msgs)
        except StreamError as exc:
            try:
                if exc.args[0][0] == "KeyError":
                    return nn  # empty
            except Exception:
                pass
            raise exc from None

        async for pr, p, d, *m in it:
            p = pl.long(pr, p)
            nn.set(p, d, MsgMeta._moat__restore(m, NotGiven))
        return nn


@pytest.mark.anyio
async def test_ls_walk(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        srv = await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        n = Node()

        async def s(p, v):
            p = P(p)
            await c.cmd(P("d.set"), p, v)
            n.set(p, v, MsgMeta(origin="Test"))

        await data(s)
        nn = await fetch(c, "a")

        assert n.get(P("a")) == nn
        await s("a.b.x", 90)
        assert n.get(P("a")) != nn


@pytest.mark.anyio
async def test_ls_save(cfg, tmp_path):
    fname = tmp_path / "test.moat"

    n = Node()
    async with Scaffold(cfg, use_servers=True) as sf:
        srv = await sf.server(init={"Hello": "there!", "test": 1})
        c = await sf.client()

        async def s(p, v):
            p = P(p)
            await c.cmd(P("d.set"), p, v)
            n.set(p, v, MsgMeta(origin="Test"))

        await data(s)
        await c.cmd(P("s.save"), path=str(fname))

    async with Scaffold(cfg, use_servers=True) as sf:
        srv = await sf.server(init={"Hello": "there!", "test": 1})
        c = await sf.client()
        nn = await fetch(c, "a")
        assert n.get(P("a")) != nn
        res = await c.cmd(P("s.load"), path=str(fname))
        nn = await fetch(c, "a")
        assert n.get(P("a")) == nn
