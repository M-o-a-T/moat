from __future__ import annotations

import anyio
import pytest
import time
import sys

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.link.client import Link
from moat.link.gate import run_gate
from moat.util import P, PathLongener, NotGiven, ungroup
from moat.lib.cmd import StreamError
from moat.lib.cmd.base import MsgSender

async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)

@pytest.mark.anyio()
async def test_gate_mqtt(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p,d in mon:
                    got.append((p,d))

        async def mon_dst(task_status):
            async with c.monitor(P("test.b")) as mon:
                got = []
                task_status.started(got)
                async for m in mon:
                    got.append((m.path,m.data))

        d_src = await sf.tg.start(mon_src)
        d_dst = await sf.tg.start(mon_dst)

        await c.d_set(P("gate.test"), dict(
            driver="mqtt",
            src=P("test.a"),
            dst=P("test.b"),
            codec="json",
            ))

        await sf.tg.start(run_gate,sf.cfg,c,"test")

        await anyio.sleep(0.2)
        a= await c.d_get(P("test.a"))
        b= await c.d_get(P("test.b"))

        yprint(dict(a=a,b=b),file=sys.stderr)

