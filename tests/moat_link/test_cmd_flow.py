"""End-to-end tests for ``moat.link.flow``."""

from __future__ import annotations

import anyio
import pytest
from io import StringIO

from moat.util import NotGiven, attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.flow import _main as flow_cmd

pytestmark = pytest.mark.anyio


async def test_flow_check_e2e_reports_stale_without_writing_errors(cfg):
    """`flow check` reports stale data but does not write `error.flow.*`."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(P("flow.state.stale"), {"_": {"timeout": 0.05}})
        await c.d_set(P("state.stale"), 1)
        await c.i_sync()
        await anyio.sleep(0.08)

        obj = attrdict(conn=c, stdout=StringIO())
        async with sf.do_watch(P("error.flow.state"), subtree=True) as res:
            await flow_cmd.check.callback.__wrapped__(obj, P("state"), False, False)
            await anyio.sleep(0.05)

        out = obj.stdout.getvalue()
        assert "state.stale" in out
        assert "Stale data" in out
        assert await res.get() == []


async def test_flow_monitor_e2e_writes_and_clears_timeout_error(cfg):
    """`flow monitor` creates and clears timeout errors."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as watcher,
    ):
        await writer.d_set(P("flow.state.live"), {"_": {"timeout": 0.05}})
        await writer.i_sync()

        obj = attrdict(conn=watcher, stdout=StringIO())
        async with (
            sf.do_watch(P("error.flow.state"), subtree=True, n=2) as evt,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(flow_cmd.monitor.callback.__wrapped__, obj, P("state"))
            await writer.d_set(P("state.live"), 10)
            await writer.i_sync()
            await anyio.sleep(0.18)
            await writer.d_set(P("state.live"), 11)
            await writer.i_sync()
            await anyio.sleep(0.18)
            await writer.d_set(P("state.live"), 12)
            await writer.i_sync()
            await anyio.sleep(0.05)
            tg.cancel_scope.cancel()

        events = await evt.get()
        assert len(events) == 2
        p1, d1 = events[0]
        assert p1 == P("live")
        assert d1["check"]["timeout"] == pytest.approx(0.05)
        assert d1["data"] in (10, 11)

        p2, d2 = events[1]
        assert p2 == P("live")
        assert d2 is NotGiven


async def test_flow_check_e2e_reports_unchanged_data(cfg):
    """`flow check` reports unchanged data via ``maxsame`` but does not write errors."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(P("flow.state.frozen"), {"_": {"maxsame": 0.05}})
        await c.d_set(P("state.frozen"), 42)
        await c.i_sync()
        await anyio.sleep(0.08)

        obj = attrdict(conn=c, stdout=StringIO())
        async with sf.do_watch(P("error.flow.state"), subtree=True) as res:
            await flow_cmd.check.callback.__wrapped__(obj, P("state"), False, False)
            await anyio.sleep(0.05)

        out = obj.stdout.getvalue()
        assert "state.frozen" in out
        assert "Unchanged" in out
        assert await res.get() == []


async def test_flow_monitor_e2e_writes_and_clears_maxsame_error(cfg):
    """`flow monitor` creates and clears ``maxsame`` errors for unchanged data."""

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as watcher,
    ):
        await writer.d_set(P("flow.state.stuck"), {"_": {"maxsame": 0.1}})
        await writer.i_sync()

        obj = attrdict(conn=watcher, stdout=StringIO())
        async with (
            sf.do_watch(P("error.flow.state"), subtree=True, n=2) as evt,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(flow_cmd.monitor.callback.__wrapped__, obj, P("state"))

            # Let the monitor subscribe before we start writing
            await anyio.sleep(0.1)

            # Initial value
            await writer.d_set(P("state.stuck"), 10)
            await writer.i_sync()
            await anyio.sleep(0.1)

            # Same value again — triggers maxsame timer
            await writer.d_set(P("state.stuck"), 10)
            await writer.i_sync()

            # Wait for the maxsame timer to expire (> 0.1s)
            await anyio.sleep(0.2)

            # Change the value — should clear the error
            await writer.d_set(P("state.stuck"), 11)
            await writer.i_sync()
            await anyio.sleep(0.1)

            tg.cancel_scope.cancel()

        events = await evt.get()
        assert len(events) == 2

        p1, d1 = events[0]
        assert p1 == P("stuck")
        assert "maxsame" in d1["check"]
        assert d1["check"]["maxsame"] == pytest.approx(0.1)
        assert d1["data"] == 10

        p2, d2 = events[1]
        assert p2 == P("stuck")
        assert d2 is NotGiven
