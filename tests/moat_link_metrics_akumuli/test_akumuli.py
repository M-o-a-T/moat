"""Integration test for moat.link.metrics with the Akumuli backend."""

from __future__ import annotations

import anyio
import pytest
import shutil
from time import time

from asyncakumuli.mock import AkumuliTester

from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.metrics.task import task

if not shutil.which("akumulid"):
    pytestmark = pytest.mark.skip


@pytest.mark.anyio
async def test_basic(cfg, free_tcp_port_factory):
    """Metrics entries are forwarded to the Akumuli mock."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        AkumuliTester(free_tcp_port_factory(), free_tcp_port_factory()).run() as t,
    ):
        await sf.server(init="INIT")
        c = await sf.client()

        # Metrics config: "prefix" tells the task where to find the tree.
        metrics_cfg = {
            "prefix": ("metrics",),
            "server": {
                "backend": "akumuli",
                "host": "127.0.0.1",
                "port": t.TCP_PORT,
            },
        }

        # Store per-server config (can carry overrides; empty is fine).
        await c.d_set(P("metrics.test"), {"server": {"port": t.TCP_PORT}})

        # Set the source value *before* creating the entry so that
        # d_watch inside the worker sees an initial value.
        await c.d_set(P("test.one.two"), 41)

        # Create a metrics entry that maps test.one.two → series "whatever".
        await c.d_set(
            P("metrics.test.entry1"),
            {
                "source": ("test", "one", "two"),
                "series": "whatever",
                "tags": {"foo": "bar"},
                "mode": "gauge",
            },
        )
        await c.i_sync()

        # Start the metrics supervisor task.
        await sf.tg.start(task, c, metrics_cfg, "test")

        # Give the worker time to pick up the initial value.
        await anyio.sleep(0.3)

        # Update the source a couple of times.
        await c.d_set(P("test.one.two"), 42)
        await anyio.sleep(0.5)

        await c.d_set(P("test.one.two"), 43)
        await anyio.sleep(0.5)

        # Query the mock for stored data points.
        n = 0
        async for x in t.get_data("whatever", tags={}, t_start=time() - 1000, t_end=time() + 1000):
            n += 1
            assert x.value in (41, 42, 43)
            assert abs(time() - x.time) < 10
        assert n > 1
