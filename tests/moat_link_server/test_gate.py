from __future__ import annotations

import anyio
import pytest
import time
import sys
from functools import partial
from contextlib import AsyncExitStack
import mock
import trio
import copy

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.link.client import Link
from moat.link.gate import run_gate
from moat.link._data import data_get, backend_get
from moat.util import P, PathLongener, NotGiven, ungroup, yprint, combine_dict, CFG, ensure_cfg
from moat.lib.cmd import StreamError
from moat.lib.cmd.base import MsgSender
from moat.lib.codec import get_codec
from moat.kv.server import Server as KVServer
from moat.kv.client import open_client as KVClient
from moat.kv.data import data_get as kvdata_get

async def mon(c,*,task_status):
    async with c.monitor(P(':'),codec="std-cbor",subtree=True,raw=True) as mo:
        task_status.started()
        c1=get_codec("std-cbor")
        c2=get_codec("std-msgpack")
        async for msg in mo:
            try:
                data = c1.decode(msg.data)
                meta = MsgMeta.decode(msg.meta)
            except Exception:
                pass
            else:
                print("***** cbor", msg.topic,data,meta)
                continue

            try:
                data = c2.decode(msg.data)
            except Exception:
                pass
            else:
                print("***** msgp", msg.topic,data,msg.meta)
                continue

            print("***** raw ", msg.topic,msg.data,msg.meta)

@pytest.mark.anyio()
async def test_gate_mqtt(cfg):
    async with Scaffold(cfg, use_servers=True) as sf:
        # await sf.tg.start(_dump, sf)
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        cc = await sf.client()
        cm = await sf.client()
        await sf.tg.start(mon,cm)

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
        await c.i_sync()

        await sf.tg.start(run_gate,sf.cfg,c,"test")

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

otm=time.time
def tm():
    try:
        return trio.current_time()
    except RuntimeError:
        return otm()

@pytest.mark.trio()
async def test_gate_kv(cfg, autojump_clock):
    autojump_clock.autojump_threshold = .1
    async with AsyncExitStack() as ex:
        ex.enter_context(mock.patch("time.time", new=tm))
        ex.enter_context(mock.patch("time.monotonic", new=tm))

        sf = await ex.enter_async_context(Scaffold(cfg, use_servers=True))
        await sf.server(init={"Hello": "there!", "test": 123})

        cm = await sf.client()
        await sf.tg.start(mon,cm)

        URI = f"mqtt://127.0.0.1:{sf.cfg.backend.port}/"
        async def mock_get_host_port(kvs, host):
            return "127.0.0.1", sf.cfg.backend.port

        ensure_cfg("moat.link")
        ensure_cfg("moat.kv")
        TESTCFG = copy.deepcopy(CFG["kv"])
        TESTCFG.server.port = None
        TESTCFG.root = "test"
        server_ctx = client_ctx = False

        clock = trio.lowlevel.current_clock()
        try:
            clock.autojump_threshold = 0.02  # networking
        except Exception:
            pass  # test doesn't have autojump_clock fixture
        cfg = {
            "conn": {"ssl": False},
            "server": {
                "bind_default": {
                    "host": "127.0.0.1",
                    "port": 40000+(sf.cfg.backend.port+1)%10000,
                    "ssl": False,
                },
                "backend": "mqtt",
                "mqtt": {"uri": URI},
            },
        }
        cfg = combine_dict(cfg, TESTCFG)
        kvs=KVServer("KVgateTest",cfg=cfg, init=dict(KV="test server"))
        ex.enter_context(mock.patch.object(kvs, "_get_host_port", new=partial(mock_get_host_port, kvs)))

        evt=anyio.Event()
        sf.tg.start_soon(partial(kvs.serve,ready_evt=evt))
        await evt.wait()

        for host, port, *_ in kvs.ports:
            if host != "::" and host[0] == ":":
                continue
            ccfg = combine_dict(
                dict(conn=dict(host="127.0.0.1", port=port, ssl=False)),
                CFG["kv"],
            )
            kvc = await ex.enter_async_context(KVClient("test.client",**ccfg))
            break

        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d_set(P("test.a.one"),1)
        await c.d_set(P("test.a.two"),2)
        await kvc.set(P("test.b.two"),22)
        await kvc.set(P("test.b.three"),33)

        async def mon_src(task_status):
            async with c.d_watch(P("test.a")) as mon:
                got = []
                task_status.started(got)
                async for p,d in mon:
                    got.append((p,d))

        async def mon_dst(task_status):
            async with kvc.watch(P("test.b")) as mon:
                got = []
                task_status.started(got)
                async for m in mon:
                    got.append((m.path,m.value))

        d_src = await sf.tg.start(mon_src)
        d_dst = await sf.tg.start(mon_dst)

        await c.d_set(P("gate.test"), dict(
            driver="kv",
            src=P("test.a"),
            dst=P("test.b"),
            ))
        await c.i_sync()

        cfg["conn"]=dict(host="127.0.0.1",port=cfg["server"]["bind_default"]["port"])
        await sf.tg.start(run_gate,cfg,c,"test")

        await anyio.sleep(0.2)
        a= await data_get(c,P("test.a"), out=False)
        assert a==dict(one={"_":1},two={"_":2},three={"_":33})

        b= await kvdata_get(kvc,P("test.b"), out=False)
        assert b==dict(one={"_":1},two={"_":2},three={"_":33})

        # now change things
        await kvc.set(P("test.b.one"),111)
        await kvc.set(P("test.b.four"),444)
        await kvc.set(P("test.b.two"),22)
        await c.d_set(P("test.a.three"),333)
        await c.d_set(P("test.a.five"),555)
        await anyio.sleep(0.2)

        a= await data_get(c,P("test.a"), out=False)
        assert a==dict(one={"_":111},two={"_":22},three={"_":333},four={"_":444},five={"_":555})

        b= await kvdata_get(kvc,P("test.b"), out=False)
        assert b==dict(one={"_":111},two={"_":22},three={"_":333},four={"_":444},five={"_":555})


