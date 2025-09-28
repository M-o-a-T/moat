from __future__ import annotations

import anyio
import pytest
import time
import sys

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.link.client import Link
from moat.util import P, PathLongener, NotGiven, ungroup
from moat.lib.cmd import StreamError
from moat.lib.cmd.base import MsgSender


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


class Supi(Link):
    async def cmd_supi(self):
        return "Yes"

    async def stream_supa(self, msg):
        async with msg.stream_out() as s:
            await s.send(1)
            await s.send(2)
            await s.send(3)


@pytest.mark.anyio()
async def test_c2c_basic(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})

        c = await sf.client()
        s = await sf.client(cli=Supi(cfg.link, "sup"))
        await anyio.sleep(0.2)
        cln = set()
        async with c.cl().stream_in() as mm:
            async for m in mm:
                cln.add(m[0])
        assert len(cln) == 2
        assert "sup" in cln

        res = await c.cl.sup.supi()
        assert res[0] == "Yes"
        # XXX 'res' should not be a message

        nn = []
        async with c.cl.sup.supa().stream_in() as mm:
            async for m in mm:
                nn.append(m[0])
        assert nn == [1, 2, 3]


@pytest.mark.anyio()
@pytest.mark.xfail()
async def test_c2c_relay(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)
        s1, _d1 = await sf.server(init={"Hello": "there!", "test": 123})
        s2, _d2 = await sf.server()

        c1 = MsgSender(s1)
        c1.add_sub("cl")
        c2 = MsgSender(s2)
        c2.add_sub("cl")

        s = await sf.client(cli=Supi(cfg.link, "sup"))
        await anyio.sleep(0.9)

        res = await c1.cl.sup.supi()
        assert res == "Yes"

        res = await c2.cl.sup.supi()
        assert res == "Yes"
