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
from moat.link._data import data_get, backend_get
from moat.util import P, PathLongener, NotGiven, ungroup, yprint
from moat.lib.cmd import StreamError
from moat.lib.cmd.base import MsgSender
from moat.lib.codec import get_codec

async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    codec=get_codec("std-cbor")
    async with bk.monitor(P("#"), qos=0, codec="noop") as mon:
        task_status.started()
        async for msg in mon:
            try:
                d = codec.decode(msg.data)
            except Exception:
                print(msg)
            else:
                print(f"Message(topic={msg.topic!r}, data=CBOR:{d!r}, meta={msg.meta} retain={msg.retain})")

@pytest.mark.anyio()
async def test_gate_mqtt(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        cc = await sf.client()
        codec=get_codec("json")

        await c.d_set(P("test.a.one"),1)
        await c.d_set(P("test.a.two"),2)
        await c.send(P("test.b.two"),22,codec=codec, retain=True)
        await c.send(P("test.b.three"),33,codec=codec, retain=True)

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p,d in mon:
                    got.append((p,d))

        async def mon_dst(task_status):
            async with c.monitor(P("test.b"),codec=codec) as mon:
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
        a= await data_get(c,P("test.a"), out=False)
        assert a==dict(one={"_":1},two={"_":2},three={"_":33})

        b= await backend_get(cc,P("test.b"), out=False)
        assert b==dict(one={"_":b'1'},two={"_":b'22'},three={"_":b'33'})

        # now change things
        await c.send(P("test.b.one"),111,codec=codec, retain=True)
        await c.send(P("test.b.four"),444,codec=codec, retain=True)
        await c.d_set(P("test.a.three"),333)
        await c.d_set(P("test.a.five"),555)
        await anyio.sleep(0.2)

        a= await data_get(c,P("test.a"), out=False)
        assert a==dict(one={"_":111},two={"_":2},three={"_":333},four={"_":444},five={"_":555})

        b= await backend_get(cc,P("test.b"), out=False)
        assert b==dict(one={"_":b'111'},two={"_":b'22'},three={"_":b'333'},four={"_":b'444'},five={"_":b'555'})

