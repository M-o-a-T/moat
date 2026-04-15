from __future__ import annotations  # noqa: D100

import anyio
import pytest

from moat.util import NotGiven
from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.link.exceptions import OutOfDateError
from moat.link.meta import MsgMeta


@pytest.mark.anyio
async def test_get_flat_simple(cfg):
    "Check reading the current state"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="HiLo", state=True) as res:
                res = await res.get()
        assert res == []


@pytest.mark.anyio
async def test_get_flat_dyn(cfg):
    "Check reading dynamic updates, no state"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=False) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert res == []


@pytest.mark.parametrize("state", [None, NotGiven])
@pytest.mark.anyio
async def test_get_flat_full(cfg, state):
    "Check reading state plus dynamic updates"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=state) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 1
        res = res[0]
        assert res[0] == "HiLo"


@pytest.mark.anyio
async def test_get_tree_simple(cfg):
    "Check reading the current state of a tree"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="HiLo", state=True, subtree=True) as res:
                res = await res.get()
        assert res == []


@pytest.mark.anyio
async def test_get_tree_dyn(cfg):
    "Check reading a tree with dynamic updates, no state"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=False, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 1
        assert res[0][0] == P("too")
        assert res[0][1] == "Ugh3"


@pytest.mark.anyio
async def test_get_tree_full(cfg):
    "Check reading a tree with dynamic updates plus state"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        assert res[0][0] == Path()
        assert res[0][1] == "HiLo"
        assert res[1][0] == P("too")
        assert res[1][1] == "Ugh2"
        assert res[2][0] == P("too")
        assert res[2][1] == "Ugh3"


@pytest.mark.anyio
async def test_get_tree_dyn_old(cfg):
    "Check that stale data gets ignored"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        old = MsgMeta(origin="old")
        await anyio.sleep(0.05)

        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "dead", meta=old)
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        assert res[0][0] == Path()
        assert res[0][1] == "HiLo"
        assert res[1][0] == P("too")
        assert res[1][1] == "Ugh2"
        assert res[2][0] == P("too")
        assert res[2][1] == "Ugh3"


@pytest.mark.anyio
async def test_get_tree_drop(cfg):
    "Check reading a tree where state gets removed"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        with anyio.fail_after(0.5):
            async with sf.do_watch(P("test.here"), exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), NotGiven)
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        res = res[-1]
        assert res[0] == P("too")
        assert res[1] is NotGiven


@pytest.mark.anyio
async def test_set_time(cfg):
    "Check updating with timestamps"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        with pytest.raises(KeyError):
            await c.d_set(P("test.here"), "Nope0", t=True)

        await c.d.set(P("test.here"), "HiLo", t=False)
        res = await c.d.get(P("test.here"))
        assert res[0] == "HiLo"
        meta = MsgMeta.restore(res[1:])
        assert (await c.d_set(P("test.here"), "Ugh", t=meta.timestamp)) is True
        res = await c.d.get(P("test.here"))
        assert res[0] == "Ugh"
        meta = MsgMeta.restore(res[1:])
        same_meta = MsgMeta(origin="X", timestamp=meta.timestamp)
        assert (await c.d_set(P("test.here"), "Ugh", t=meta.timestamp, meta=same_meta)) is None
        with pytest.raises(OutOfDateError):
            await c.d_set(P("test.here"), "Nope1", t=meta.timestamp - 10)
        with pytest.raises(KeyError):
            await c.d_set(P("test.here"), "Nope2", t=False)
        assert (await c.d_set(P("test.here"), "Yep3", t=True)) is True
        res = await c.d.get(P("test.here"))
        assert res[0] == "Yep3"


@pytest.mark.anyio
async def test_set_d_direct(cfg):
    "Check updating with d_direct"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!", "test": 123}),
        sf.client_() as c,
    ):
        await c.d_.test.foo.bar(42)
        assert (await c.d_get(P("test.foo.bar"))) == 42
        (res,) = await c.d_.test.foo.bar()
        assert res == 42
        async with c.sub_at(P("d_.test.foo.bar")) as cc:
            (res,) = await cc()
            assert res == 42
        async with c.sub_at(P("d_.test")) as cc:
            (res,) = await cc(p=P("foo.bar"))
            assert res == 42

        await c.d_.test.foo.bar(NotGiven)
        with pytest.raises(KeyError):
            await c.d_get(P("test.foo.bar"))
        with pytest.raises(KeyError):
            await c.d_.test.foo.bar()


@pytest.mark.anyio
async def test_unix_socket_connect(cfg):
    "Client connects directly via configured Unix socket path"
    async with anyio.TemporaryDirectory() as tmpdir:
        sock_path = f"{tmpdir}/test.sock"

        # Start server with both TCP (for MQTT announcement) and Unix socket.
        # The scaffold rewrites ports.main.port to 0, so we include it.
        server_patch = {
            "server": {
                "ports": {
                    "main": {"host": "0.0.0.0", "port": 0},  # noqa:S104
                    "unix": {"port": sock_path},
                }
            }
        }
        async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(server_patch, init={}),
            sf.client_({"client": {"path": sock_path}}) as c,
        ):
            await c.d_set(P("test.via_socket"), "hello")
            await c.i_sync()
            assert (await c.d_get(P("test.via_socket"))) == "hello"


@pytest.mark.anyio
async def test_unix_socket_fallback(cfg):
    "Client falls back to MQTT announcement when configured socket is absent"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={}),
        sf.client_({"client": {"path": "/nonexistent/path/test.sock"}}) as c,
    ):
        # Client should have connected via MQTT announcement despite bad socket path
        assert c.link.server_name is not None
        await c.d_set(P("test.via_fallback"), "world")
        await c.i_sync()
        assert (await c.d_get(P("test.via_fallback"))) == "world"
