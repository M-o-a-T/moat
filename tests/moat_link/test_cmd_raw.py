"""
Tests for ``moat link raw`` commands.
"""

from __future__ import annotations

import platform
import pytest

from moat.util import ungroup
from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio

# a short wait for pings
STALE = "-s moat.link.timeout.ping.stale =2 "


async def test_raw_test(cfg):
    "'raw test' shows the root dataset and the server broadcast, and checks pings."
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        # This client stands in for a server and the cleanup task.
        c = await sf.client(cfg=dict(timeout=dict(ping=dict(every=0.5))))
        ann = dict(id=c.id, up=True)
        await c.send(P(":R.run.host"), ann, retain=True)
        await c.send(P(":R.run.host.th.moat.link.server"), ann, retain=True)

        r = await sf.run(STALE + "link raw test")
        assert "Root dataset:" in r.stdout
        assert "Hello: there!" in r.stdout
        assert "Server broadcast:" in r.stdout
        assert "Server th: alive" in r.stdout
        # the test client's run.id message names this host
        assert f"Cleanup task (run.host) on {platform.node()}: alive" in r.stdout

        # a server that doesn't ping
        await c.send(
            P(":R.run.host.gone.moat.link.server"),
            dict(id="_no_such_client", up=True),
            retain=True,
        )
        with pytest.raises(SystemExit) as err, ungroup:
            await sf.run(STALE + "link raw test")
        assert err.value.code == 1


async def test_raw_test_nothing(cfg):
    "Without announced servers or cleanup task, 'raw test' fails."
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"Hello": "there!"})
        with pytest.raises(SystemExit) as err, ungroup:
            await sf.run(STALE + "link raw test")
        assert err.value.code == 1
