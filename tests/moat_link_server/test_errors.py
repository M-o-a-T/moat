from __future__ import annotations  # noqa: D100

import anyio
import pytest
import time

from moat.util import NotGiven, P, Path
from moat.lib.cmd import RemoteError
from moat.link._test import Scaffold


@pytest.mark.anyio
async def test_simple(cfg):
    "Check sending an info text"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        t1 = time.time()
        async with sf.do_watch(Path("error"), meta=True, subtree=True) as r:
            await c.e_info(P("test.here"), "TestError", state="bad", help="me!")
            await anyio.sleep(0.2)
        r = await r.get()
        t2 = time.time()
        assert len(r) == 1
        p, d, m = r[0]
        assert p == P("test.here")
        assert d["state"] == "bad"
        assert t1 < m.timestamp < t2


@pytest.mark.anyio
async def test_exc(cfg):
    "Check sending+acking an exception"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        t1 = time.time()
        async with sf.do_watch(Path("error"), meta=True, subtree=True) as r:
            try:
                raise KeyError("abc")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, missing="key")
                err = exc
            await anyio.sleep(0.2)
            await c.e_exc(P("test.here"), err, missing="key", foo="again")
            await anyio.sleep(0.2)
            await c.e_ack(P("test.here"), this="that")
            await anyio.sleep(0.2)
        r = await r.get()
        t2 = time.time()
        assert len(r) == 3
        p, d, m = r[0]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert "this" not in d
        assert isinstance(d["_exc"], KeyError)
        assert "_bt" not in d
        assert "_first" not in d
        assert t1 < m.timestamp < t2
        p, d, m2 = r[1]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert d["foo"] == "again"
        assert "_ack" not in d
        assert d["_n"] == 2
        assert d["_first"] == m.timestamp
        assert isinstance(d["_exc"], KeyError)
        assert "_bt" not in d
        assert m.timestamp < m2.timestamp < t2
        p, d, m3 = r[2]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert d["this"] == "that"
        assert d["foo"] == "again"
        assert d["_ack"]
        assert d["_first"] == m.timestamp
        assert d["_n"] == 2
        assert isinstance(d["_exc"], KeyError)
        assert "_bt" not in d
        assert m2.timestamp < m3.timestamp < t2


@pytest.mark.anyio
async def test_exc_np(cfg):
    "Check sending an un-proxied exception"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        t1 = time.time()
        async with sf.do_watch(Path("error"), meta=True, subtree=True) as r:
            try:
                raise SyntaxError("abc")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, missing="key")
            await anyio.sleep(0.2)
        r = await r.get()
        t2 = time.time()
        assert len(r) == 1
        p, d, m = r[0]
        assert p == P("test.here")
        assert d["missing"] == "key"
        assert isinstance(d["_exc"], RemoteError)
        assert d["_exc"].args[0] == "SyntaxError"
        assert d["_exc"].args[1] == "abc"
        assert "_bt" not in d
        assert t1 < m.timestamp < t2


@pytest.mark.anyio
async def test_exc_clear(cfg):
    "Check clearing an exception"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        t1 = time.time()
        async with sf.do_watch(Path("error"), meta=True, subtree=True) as r:
            try:
                raise RuntimeError("dud")
            except Exception as exc:
                await c.e_exc(P("test.here"), exc, some="data")
            await anyio.sleep(0.1)
            d, m = await c.d_get(P("error.test.here"), meta=True)
            assert d["some"] == "data"
            assert isinstance(d["_exc"], RemoteError)
            assert "_bt" not in d
            assert t1 < m.timestamp

            await c.e_ok(P("test.here"), situation="normal")
            await anyio.sleep(0.2)
        r = await r.get()
        t2 = time.time()
        assert len(r) == 2
        p, d, m = r[0]
        assert p == P("test.here")
        assert d["some"] == "data"
        assert isinstance(d["_exc"], RemoteError)
        assert "_bt" not in d
        assert t1 < m.timestamp < t2

        p, d, m2 = r[1]
        assert p == P("test.here")
        assert d is NotGiven
        assert m.timestamp < m2.timestamp < t2

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))


@pytest.mark.anyio
async def test_wrap_ok(cfg):
    "Check wrapping success"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        async with (
            sf.do_watch(Path("error"), meta=True, subtree=True) as r,
            c.e_wrap(P("test.here"), help="me?") as mon,
        ):
            await mon.send("tree")
            with pytest.raises(KeyError):
                await c.d_get(P("error.test.here"))
            await anyio.sleep(0.2)

        r = await r.get()
        assert len(r) == 0

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))


@pytest.mark.anyio
async def test_errlog(cfg):
    "Check wrapping an exception (and clearing it the same way)"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        t1 = time.time()
        async with (
            sf.do_watch(P("error"), meta=True, subtree=True) as r,
            sf.do_watch(P("run.error"), meta=True, subtree=True, break_=False) as errlog,
        ):
            try:
                async with c.e_wrap(P("test.here"), help="me?") as mon:
                    await mon.send("one")
                    await mon.send("two")
                    raise RuntimeError("ESandD")
            except* RuntimeError:
                await anyio.sleep(0.2)
            else:
                raise AssertionError("did not pass exception")

            d, m = await c.d_get(P("error.test.here"), meta=True)
            assert d["help"] == "me?"
            assert d["_log"] == [["one"], ["two"]]
            assert isinstance(d["_exc"], RuntimeError)
            assert "_bt" not in d
            assert t1 < m.timestamp

            async with c.e_wrap(P("test.here"), help="me too") as mon:
                await mon.send("one")
                await mon.send("two")

            await anyio.sleep(0.2)

        r = await r.get()
        t2 = time.time()
        assert len(r) == 2
        p, d, m = r[0]
        assert p == P("test.here")
        assert d["help"] == "me?"
        assert isinstance(d["_exc"], RuntimeError)
        assert d["_log"] == [["one"], ["two"]]
        assert "_bt" not in d
        assert t1 < m.timestamp < t2

        p, d, m2 = r[1]
        assert p == P("test.here")
        assert d is NotGiven
        assert m.timestamp < m2.timestamp < t2

        with pytest.raises(KeyError):
            await c.d_get(P("error.test.here"))

    rdr = await errlog.get()
    rdr = iter(rdr)

    m = next(rdr)
    assert m[0] == P("test.here")
    assert m[1]["help"] == "me?"
    assert "_ok" not in m[2]

    m = next(rdr)
    assert m[0] == P("test.here")
    assert m[1]["help"] == "me too"
    assert m[1]["_ok"] is True

    with pytest.raises(StopIteration):
        next(rdr)
