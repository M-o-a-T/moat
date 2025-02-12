from __future__ import annotations

import anyio
import pytest
import time

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.util import P


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


@pytest.mark.anyio
async def test_basic(cfg):
    evt = anyio.Event()
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)

        async def cl(*, task_status):
            c = await sf.client()

            async with c.monitor(P("test.here")) as mon:
                task_status.started()
                async for m in mon:
                    assert m.data == "Hello"
                    assert m.meta.origin == "me!"
                    t = time.time()
                    assert t - 1 < m.meta.timestamp < t
                    evt.set()
                    break

        srv = await sf.server(init={"Hello": "there!", "test": 123})
        await sf.tg.start(cl)

        c = await sf.client()
        r = await c.cmd(P("i.ping"),"pling")
        assert r.args == ['乓', 'pling'], r

        om = MsgMeta(origin="me!")
        await c.send(P("test.here"), "Hello", meta=om)
        with anyio.fail_after(1):
            await evt.wait()
