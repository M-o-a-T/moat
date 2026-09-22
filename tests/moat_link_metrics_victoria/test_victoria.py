"""Integration test for moat.link.metrics with the VictoriaMetrics backend."""

from __future__ import annotations

import anyio
import pytest
import shutil
from time import time, time_ns

from asyncvictoria.mock import VictoriaTester

import moat.link.metrics.backend.victoria as vb
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.metrics.task import task

if not shutil.which("victoria-metrics"):
    pytestmark = pytest.mark.skip

vb.MOCK_DELTA = 3700 * 10**9  # nanoseconds
vb.MOCK_TM = time_ns() - 2 * vb.MOCK_DELTA  # nanoseconds


@pytest.mark.anyio
async def test_basic(cfg):
    """Metrics entries are forwarded to the VictoriaMetrics mock."""
    # VictoriaTester manages its own port allocation internally (PID-based),
    # since victoria-metrics is an external process that needs the port in its config.
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        VictoriaTester().run() as t,
    ):
        await sf.server(init="INIT")
        c = await sf.client()
        mcfg = cfg.link.metrics
        assert mcfg.backend == "victoria", "Shipped default backend must be victoria for this test"

        # Store per-server config (can carry overrides; empty is fine).
        await c.d_set(mcfg.prefix / "test", {"server": {"port": t.TCP_PORT}})

        # Set the source value *before* creating the entry so that
        # d_watch inside the worker sees an initial value.
        await c.d_set(P("test.one.two"), 41)

        # Create a metrics entry that maps test.one.two → series "whatever".
        await c.d_set(
            mcfg.prefix / "test" / "entry1",
            {
                "source": ("test", "one", "two"),
                "series": "whatever",
                "tags": {"foo": "bar"},
                "mode": "gauge",
            },
        )
        await c.i_sync()

        # Start the metrics supervisor task.
        await sf.tg.start(task, c, mcfg, "test")

        # Give the worker time to pick up the initial value.
        await anyio.sleep(0.3)

        # Update the source a couple of times.
        await c.d_set(P("test.one.two"), 42)
        await anyio.sleep(1)
        await t.flush()

        await c.d_set(P("test.one.two"), 43)
        await anyio.sleep(1)
        await t.flush()
        await anyio.sleep(2)

        # Query the mock for the stored data points.
        #
        # This uses the raw-sample export API, not a range query: the latter
        # is a rollup API, so VictoriaMetrics carries the last sample forward
        # onto every step of the grid and we'd see one point per step instead
        # of the three points actually written.
        seen = []
        async for x in t.get_raw_data(
            "whatever", tags={}, t_start=time() - 30000, t_end=time() + 30000
        ):
            seen.append(x.value)
        assert seen == [41, 42, 43]
