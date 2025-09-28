"basic client tests"

from __future__ import annotations

import anyio
import pytest
import time

from moat.link._test import Scaffold
from moat.link.meta import MsgMeta
from moat.util import P


@pytest.mark.anyio
async def test_simple(cfg):
    "simple client-to-client comm test"
    async with Scaffold(cfg, use_servers=False) as sf:

        async def cl(*, task_status):
            c = await sf.client()

            async with c.monitor(P("test.here")) as mon:
                evt = anyio.Event()
                task_status.started(evt)
                async for m in mon:
                    assert m.data == "Hello"
                    assert m.meta.origin == "me!"
                    t = time.time()
                    assert t - 1 < m.meta.timestamp < t
                    evt.set()
                    break

        evt = await sf.tg.start(cl)
        c = await sf.client()
        om = MsgMeta(origin="me!")
        await c.send(P("test.here"), "Hello", meta=om, retain=True)
        with anyio.fail_after(1):
            await evt.wait()
