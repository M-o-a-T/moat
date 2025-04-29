from __future__ import annotations

import anyio
import pytest
import time
import sys
from contextlib import asynccontextmanager

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.util import P, PathLongener, NotGiven, ungroup, ValueEvent, Path
from moat.util.msg import MsgReader
from moat.lib.cmd import StreamError, RemoteError


@asynccontextmanager
async def do_watch(sf,*a,**kw):
    """
    Log the error stream. When @e1 is set, stops and sets @e2.

    All other args+kw are forwarded to `Link.d_watch`.
    """
    async with anyio.create_task_group() as tg, sf.client_() as c:
        res=[]
        async def work(task_status):
            with anyio.CancelScope() as sc:
                async with c.d_watch(Path("error"),*a,subtree=True,**kw) as mon:
                    task_status.started(sc)
                    async for p,d,m in mon:
                        res.append((p,d,m))

        cs = await tg.start(work)
        yield res
        cs.cancel()


@pytest.mark.anyio()
async def test_simple(cfg):
    "Check sending an info text"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r:
            await c.e_info(P("test.here"), "TestError", state="bad", help="me!")
            await anyio.sleep(0.2)
        t2 = time.time()
        assert len(r) == 1
        p,d,m = r[0]
        assert p == P("test.here")
        assert d["state"] == "bad"
        assert t1<m.timestamp<t2


@pytest.mark.anyio()
async def test_exc(cfg):
    "Check sending an exception"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r:
            try:
                raise KeyError("abc")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, missing="key")
            await anyio.sleep(0.2)
        t2 = time.time()
        assert len(r) == 1
        p,d,m = r[0]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert isinstance(d["_exc"],KeyError)
        assert "_bt" not in d
        assert t1<m.timestamp<t2


@pytest.mark.anyio()
async def test_exc_np(cfg):
    "Check sending an un-proxied exception"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r:
            try:
                raise SyntaxError("abc")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, missing="key")
            await anyio.sleep(0.2)
        t2 = time.time()
        assert len(r) == 1
        p,d,m = r[0]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert isinstance(d["_exc"],RemoteError)
        assert d["_exc"].args[0] == "SyntaxError"
        assert d["_exc"].args[1] == "abc"
        assert "_bt" not in d
        assert t1<m.timestamp<t2


@pytest.mark.anyio()
async def test_exc_clear(cfg):
    "Check clearing an exception"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r:
            try:
                raise RuntimeError("dud")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, some="data")
            await anyio.sleep(0.1)
            d,m=await c.d_get(P("error.test.here"),meta=True)
            assert d["some"] == "data"
            assert isinstance(d["_exc"],RemoteError)
            assert "_bt" not in d
            assert t1<m.timestamp

            await c.e_ok(P("test.here"), situation="normal")
            await anyio.sleep(0.2)
        t2 = time.time()
        assert len(r) == 2
        p,d,m = r[0]
        assert p == P("test.here")
        assert d["some"] == "data"
        assert isinstance(d["_exc"],RemoteError)
        assert "_bt" not in d
        assert t1<m.timestamp<t2

        p,d,m2 = r[1]
        assert p == P("test.here")
        assert d is NotGiven
        assert m.timestamp<m2.timestamp<t2

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))

@pytest.mark.anyio()
async def test_wrap_ok(cfg):
    "Check wrapping success"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r, c.e_wrap(P("test.here"), help="me?") as mon:
            await mon.send("tree")
            with pytest.raises(KeyError):
                await c.d_get(P("error.test.here"))
            await anyio.sleep(0.2)

        t2 = time.time()
        assert len(r) == 0

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))

@pytest.mark.anyio()
async def test_wrap_bad(cfg,tmp_path):
    "Check wrapping an exception (and clearing it the same way)"
    epath = tmp_path/"errs"
    cfg.link.server.errlog = str(epath)
    epath=anyio.Path(epath)
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        t1 = time.time()
        async with do_watch(sf) as r:
            try:
                async with c.e_wrap(P("test.here"), help="me?") as mon:
                    await mon.send("one")
                    await mon.send("two")
                    raise RuntimeError("ESandD")
            except* RuntimeError:
                await anyio.sleep(0.2)
            else:
                assert False,"did not pass exception"

            d,m=await c.d_get(P("error.test.here"),meta=True)
            assert d["help"] == "me?"
            assert d["_log"] == [["one"],["two"]]
            assert isinstance(d["_exc"],RuntimeError)
            assert "_bt" not in d
            assert t1<m.timestamp

            async with c.e_wrap(P("test.here"), help="me too") as mon:
                await mon.send("one")
                await mon.send("two")

            await anyio.sleep(0.2)

        t2 = time.time()
        assert len(r) == 2
        p,d,m = r[0]
        assert p == P("test.here")
        assert d["help"] == "me?"
        assert isinstance(d["_exc"],RuntimeError)
        assert d["_log"] == [["one"],["two"]]
        assert "_bt" not in d
        assert t1<m.timestamp<t2

        p,d,m2 = r[1]
        assert p == P("test.here")
        assert d is NotGiven
        assert m.timestamp<m2.timestamp<t2

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))

    from moat.util.cbor import CBOR_TAG_MOAT_FILE_ID,CBOR_TAG_MOAT_FILE_END,CBOR_TAG_MOAT_CHANGE
    async with MsgReader(epath, codec="std-cbor") as rd:
        rdr = aiter(rd)
        m = await anext(rdr)
        assert m.tag==CBOR_TAG_MOAT_FILE_ID
        assert m.value[1]["state"] is None
        assert m.value[1]["mode"] == "error"

        m = await anext(rdr)
        assert m.tag==CBOR_TAG_MOAT_CHANGE
        assert m.value["state"] is False
        assert m.value["mode"] == "error"

        m = await anext(rdr)
        assert m[0] == 0
        assert m[1] == P("test.here")
        assert m[2]["help"] == "me?"
        assert "_ok" not in m[2]

        m = await anext(rdr)
        assert m[0] == 2
        assert m[1] == []
        assert m[2]["help"] == "me too"
        assert m[2]["_ok"] is True

        m = await anext(rdr)
        assert m.tag==CBOR_TAG_MOAT_FILE_END
        assert m.value["mode"] == "cancel"

        with pytest.raises(StopAsyncIteration):
            await anext(rdr)

