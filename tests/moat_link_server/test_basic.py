from __future__ import annotations  # noqa: D100

import anyio
import logging
import pytest
import time

from moat.util import NotGiven
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.hello import Hello
from moat.link.meta import MsgMeta
from moat.link.node import Node


async def _dump(sf, *, task_status):
    bk = await sf.backend(name="mon")
    async with bk.monitor(P("#"), qos=0) as mon:
        task_status.started()
        async for msg in mon:
            print(msg)


@pytest.mark.anyio
async def test_ls_basic(cfg):  # noqa: D103
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

        await sf.server(init={"Hello": "there!", "test": 123})
        await sf.tg.start(cl, "Hello")

        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"], r
        a, b = r  # we can iterate the result to get at the data
        assert (a, b) == ("乓", "pling"), (a, b)

        om = MsgMeta(origin="me!")
        await c.send(P(":R.test.here"), "Hello", meta=om, retain=False)
        with anyio.fail_after(1):
            await evt.wait()


@pytest.mark.anyio
async def test_ls_legacy_hello_fallback(cfg, monkeypatch):
    "A client without RPC auth support falls back to legacy Hello/auth."
    orig_modes = Hello._rpc_modes  # noqa: SLF001

    def _rpc_modes(self):
        if self.rpc_auth_server is False:
            return ()
        return orig_modes(self)

    monkeypatch.setattr(Hello, "_rpc_modes", _rpc_modes)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"]


@pytest.mark.anyio
async def test_ls_legacy_hello_beats_delayed_rpc_reject(cfg, monkeypatch):
    "Server accepts legacy hello and falls back even if the :n rejection arrives late."
    orig_modes = Hello._rpc_modes  # noqa: SLF001
    orig_handle = Hello.handle
    saw_late_reject = False
    saw_server_fallback = False

    def _rpc_modes(self):
        if self.rpc_auth_server is False:
            return ()
        return orig_modes(self)

    async def _handle(self, msg, rcmd, *prefix):
        nonlocal saw_late_reject, saw_server_fallback
        if (
            self.rpc_auth_server is True
            and self._rpc_in is not None
            and len(rcmd) == 2
            and rcmd[-1] == "i"
            and rcmd[0] == "hello"
        ):
            saw_server_fallback = True
        if self.rpc_auth_server is False and self._rpc_in is None and rcmd and rcmd[-1] is None:
            saw_late_reject = True
            await anyio.sleep(0.05)
        return await orig_handle(self, msg, rcmd, *prefix)

    monkeypatch.setattr(Hello, "_rpc_modes", _rpc_modes)
    monkeypatch.setattr(Hello, "handle", _handle)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"]
        await c.i_sync()
        await anyio.sleep(0.1)
        r = await c.cmd(P("i.乒"), "plong")
        assert r.args == ["乓", "plong"]

    assert saw_late_reject
    assert saw_server_fallback


@pytest.mark.anyio
async def test_ls_client_fallback_on_remote_no_helloauth(cfg, monkeypatch, caplog):
    "Client falls back to legacy Hello if RPC auth gets a remote No Hello/Auth error first."
    orig_modes = Hello._rpc_modes  # noqa: SLF001
    orig_run = Hello.run

    def _rpc_modes(self):
        if self.rpc_auth_server is True:
            return ()
        return orig_modes(self)

    async def _run(self, sender, **kw):
        if self.rpc_auth_server is True:
            await anyio.sleep(0.05)
        return await orig_run(self, sender, **kw)

    monkeypatch.setattr(Hello, "_rpc_modes", _rpc_modes)
    monkeypatch.setattr(Hello, "run", _run)
    caplog.set_level(logging.WARNING)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"]

    assert not any("Link failed:" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_ls_client_fallback_if_hello_precedes_nohelloauth(cfg, monkeypatch, caplog):
    "Client fallback must not time out if legacy hello completes before :n gets rejected."
    orig_modes = Hello._rpc_modes  # noqa: SLF001
    orig_handle = Hello.handle
    saw_delayed_nohelloauth = False

    def _rpc_modes(self):
        if self.rpc_auth_server is True:
            return ()
        return orig_modes(self)

    async def _handle(self, msg, rcmd, *prefix):
        nonlocal saw_delayed_nohelloauth
        if self.rpc_auth_server is True and rcmd and rcmd[-1] is None:
            saw_delayed_nohelloauth = True
            await anyio.sleep(0.05)
        return await orig_handle(self, msg, rcmd, *prefix)

    monkeypatch.setattr(Hello, "_rpc_modes", _rpc_modes)
    monkeypatch.setattr(Hello, "handle", _handle)
    caplog.set_level(logging.WARNING)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()
        r = await c.cmd(P("i.乒"), "pling")
        assert r.args == ["乓", "pling"]

    assert saw_delayed_nohelloauth
    assert not any("Link failed:" in r.message for r in caplog.records)


async def data(s):  # noqa: D103
    await s("a.b.e", 10)
    await s("a.b.f", 11)
    await s("a.b.g.h", 12)
    await s("a.b.g.o", 121)
    await s("a.b.i", 13)
    await s("a.b.j", 14)
    await s("a.c", 15)
    await s("a.c.d", 16)
    await s("a.b.d", 17)


async def fetch(c, p):  # noqa: D103
    async with c.d_watch(P(p), subtree=True, meta=True, state=True) as mon:
        return await mon.get_node()


@pytest.mark.anyio
async def test_ls_walk(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
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
async def test_ls_save(cfg, tmp_path):  # noqa: D103
    fname = tmp_path / "test.moat"

    n = Node()
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 1})
        c = await sf.client()

        async def s(p, v):
            p = P(p)
            await c.cmd(P("d.set"), p, v)
            n.set(p, v, MsgMeta(origin="Test"))

        await data(s)
        await c.cmd(P("s.save"), str(fname))
        nnn = await fetch(c, "a")

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 2})
        c = await sf.client()
        try:
            nn = await fetch(c, "a")
        except KeyError:
            pass  # not present
        else:
            if nn.data_ is not NotGiven or list(nn.keys()):
                raise ValueError("Data in node")

        await c.cmd(P("s.load"), str(fname))
        nn = await fetch(c, "a")
        assert nn == nnn


@pytest.mark.anyio
async def test_walk(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d.set(P("a"), 1)
        await c.d.set(P("a.b"), 12)
        await c.d.set(P("a.b.c"), 123)
        await c.d.set(P("a.b.c.d"), 1234)
        await c.d.set(P("a.b.c.e"), 1235)

        async def chk(want, path, **kw):
            has = set()
            async with c.d_walk(P(path), **kw) as mon:
                async for _p, d in mon:
                    has.add(d)
            assert has == want, (path, has, want, kw)

        await chk({1, 12, 123, 1234, 1235}, "a")
        await chk({123, 1234, 1235}, "a", min_depth=2)
        await chk({1, 12, 123}, "a", max_depth=2)
        await chk({1, 12}, "a", max_depth=1)
        await chk({12, 123}, "a.b", max_depth=1)


@pytest.mark.anyio
async def test_delete(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d.set(P("a"), 1)
        await c.d.set(P("a.b"), 12)
        await c.d.set(P("a.b.c"), 123)
        await c.d.set(P("a.b.c.d"), 1234)
        await c.d.set(P("a.b.c.e"), 1235)

        async def chk(want, path):
            if want is NotGiven:
                with pytest.raises(KeyError):
                    await c.d.get(P(path))
            else:
                res = await c.d.get(P(path))
                assert res[0] == want, (res, want)

        await chk(1, "a")
        await chk(12, "a.b")
        await c.d.delete(P("a.b"))
        await chk(NotGiven, "a.b")
        await chk(123, "a.b.c")

        await c.d.delete(P("a"), rec=True)
        await chk(NotGiven, "a")
        await chk(NotGiven, "a.b")
        await chk(NotGiven, "a.b.c")
        await chk(NotGiven, "a.b.c.e")


@pytest.mark.anyio
async def test_id(cfg):
    "check that the client id test works"
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})

        async def cl(*, task_status):
            c = await sf.client()
            await c.i_sync()
            evt = anyio.Event()
            task_status.started((evt, c.id))
            await evt.wait()

        evt, id = await sf.tg.start(cl)
        c = await sf.client()
        assert not await c.i_checkid("FooBar")
        assert await c.i_checkid(id)
        assert await c.i_checkid(c.id)
        evt.set()


@pytest.mark.anyio
async def test_collate(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d.set(P("a"), dict(x=2))
        await c.d.set(P("a.b"), dict(y=3))
        await c.d.set(P("a.b.f.c"), dict(x=..., z=5))
        await c.d.set(P("a.b.f.c.d"), dict(y=4))
        await c.d.set(P("a.b.f.c.e"), dict())

        async def chk(path, want):
            if want is NotGiven:
                with pytest.raises(KeyError):
                    await c.d.get(P(path))
            else:
                res = await c.d.collect(P(path)[:1], P(path)[1:])
                assert res.kw == want, (res, want)

        await chk("a", dict(x=2))
        await chk("a.b", dict(y=3))
        await chk("a.b.u", dict(y=3))
        await chk("a.b.f", dict())
        await chk("a.b.f.c", dict(z=5))
        await chk("a.b.f.c.e", dict())
        await chk("a.b.f.c.d", dict(y=4))
        await chk("a.b.f.c.d.u", dict(y=4))


@pytest.mark.anyio
async def test_asdict(cfg):  # noqa: D103
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!", "test": 123})
        c = await sf.client()

        await c.d.set(P("a"), dict(x=2))
        await c.d.set(P("a.b.c"), dict(z=dict(v=5)))

        async with c.as_dict(P("a")) as a:
            assert a.x == 2
            assert a.b.c.z.v == 5
            with pytest.raises(AttributeError):
                a.b.y  # noqa:B018

            @sf.tg.start_soon
            async def pset():
                await c.d.set(P("a.b"), dict(y=3))

            with anyio.fail_after(0.2):
                await a.wait_
            assert a.b.y == 3
