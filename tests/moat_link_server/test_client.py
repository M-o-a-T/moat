from __future__ import annotations

import anyio
import pytest
import time
import sys
from contextlib import asynccontextmanager

from moat.link.meta import MsgMeta
from moat.link._test import Scaffold
from moat.link.node import Node
from moat.util import P, PathLongener, NotGiven, ungroup, Path
from moat.lib.cmd import StreamError


@pytest.mark.anyio()
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

        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="HiLo", state=True) as res:
                res = await res.get()
        assert res == []


@pytest.mark.anyio()
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

        t=anyio.current_time()
        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=False) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert res == []


@pytest.mark.parametrize("state", [None, NotGiven])
@pytest.mark.anyio()
async def test_get_flat_full(cfg,state):
    "Check reading state plus dynamic updates"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        t=anyio.current_time()
        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=state) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 1
        res = res[0]
        assert res[0] == "HiLo"


@pytest.mark.anyio()
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

        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="HiLo", state=True, subtree=True) as res:
                res = await res.get()
        assert res == []


@pytest.mark.anyio()
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

        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=False, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 1
        assert res[0][0] == Path("too")
        assert res[0][1] == "Ugh3"


@pytest.mark.anyio()
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

        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        assert res[0][0] == Path()
        assert res[0][1] == "HiLo"
        assert res[1][0] == Path("too")
        assert res[1][1] == "Ugh2"
        assert res[2][0] == Path("too")
        assert res[2][1] == "Ugh3"


@pytest.mark.anyio()
async def test_get_tree_dyn_old(cfg):
    "Check that stale data gets ignored"
    async with (
            Scaffold(cfg, use_servers=True) as sf,
            sf.server_(init={"Hello": "there!", "test": 123}),
            sf.client_() as c,
        ):
        old = MsgMeta(origin="old")
        await anyio.sleep(.05)

        await c.d_set(P("test.here"), "HiLo")
        await c.d_set(P("test.here.too"), "Ugh2")
        await c.i_sync()

        t=time.time()
        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), "dead",meta=old)
                await c.d_set(P("test.here.too"), "Ugh3")
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        assert res[0][0] == Path()
        assert res[0][1] == "HiLo"
        assert res[1][0] == Path("too")
        assert res[1][1] == "Ugh2"
        assert res[2][0] == Path("too")
        assert res[2][1] == "Ugh3"


@pytest.mark.anyio()
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

        with anyio.fail_after(.2):
            async with sf.do_watch(P("test.here"),exp="End", state=None, subtree=True) as res:
                await c.i_sync()
                await c.d_set(P("test.here.too"), NotGiven)
                await c.i_sync()
                await c.d_set(P("test.here"), "End")
                res = await res.get()
        assert len(res) == 3
        res = res[-1]
        assert res[0] == Path("too")
        assert res[1] is NotGiven


