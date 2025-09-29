from __future__ import annotations  # noqa: D100

import anyio
import pytest
import sys
import time

from moat.util import P
from moat.link._test import Scaffold
from moat.link.meta import MsgMeta


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


@pytest.mark.anyio
async def test_watch_basic(cfg):  # noqa: D103
    evt = anyio.Event()
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)

        async def cl(end, *, task_status):
            c = await sf.client()
            evt = anyio.Event()

            async with c.d_watch(P("test.here"), subtree=True, meta=True) as mon:
                task_status.started(evt)
                async for p, d, m in mon:
                    print("GOT", p, d, m, file=sys.stderr)
                    assert m.origin == "me!"
                    t = time.time()
                    assert t - 1 < m.timestamp < t
                    if d == end:
                        evt.set()
                        break

        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.send(P(":R.test.here.before"), "One", meta=MsgMeta(origin="me!"), retain=True)
        await c.send(P(":R.test.here.both"), "Two", meta=MsgMeta(origin="me!"), retain=True)

        evt = await sf.tg.start(cl, "End")

        await c.send(P(":R.test.here.both"), "Three", meta=MsgMeta(origin="me!"), retain=True)
        await c.send(P(":R.test.here.after"), "Four", meta=MsgMeta(origin="me!"), retain=True)

        await c.send(P(":R.test.here"), "End", meta=MsgMeta(origin="me!"), retain=True)
        await evt.wait()


@pytest.mark.anyio
async def test_watch_mon(cfg):  # noqa: D103
    evt = anyio.Event()
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)

        async def cl(end, *, task_status):
            end  # noqa:B018

            c = await sf.client()
            evt = anyio.Event()

            async with c.d_watch(P("test.here"), subtree=True, meta=True) as mon:
                node = await mon.get_node()
                assert node["before"].data == "One"
                assert node["both"].data == "Two"
                task_status.started(evt)
                await evt.wait()
                assert node["both"].data == "Three"
                assert node["after"].data == "Four"

        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.send(P(":R.test.here.before"), "One", meta=MsgMeta(origin="me!"), retain=True)
        await c.send(P(":R.test.here.both"), "Two", meta=MsgMeta(origin="me!"), retain=True)

        await c.i_sync()
        evt = await sf.tg.start(cl, "End")

        await c.send(P(":R.test.here.both"), "Three", meta=MsgMeta(origin="me!"), retain=True)
        await c.send(P(":R.test.here.after"), "Four", meta=MsgMeta(origin="me!"), retain=True)
        await anyio.sleep(0.2)

        evt.set()
