"""Regression test: a joining server must sync a large tree from a peer.

Exposes the flow-control stall in the server-to-server ``d.walk`` sync.
``_sync_one`` pulls the peer's tree via a flow-controlled stream; at scale the
credit accounting/forwarding between the consumer's ``Msg`` and the producer's
handler ``Msg`` (relayed through the ``HandlerStream`` hop) breaks down: the
producer exhausts its window and blocks at ``_flo=0`` while the consumer waits
for the next item, deadlocking until ``server.timeout.startup``.

The earlier initial-credit race fix let *more* data flow, but large dumps
still don't complete.  This test populates a sizable tree and asserts the
joining server starts (i.e. the sync finished) within a bounded time.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_joining_server_syncs_large_tree(cfg):
    """A second server must finish syncing a large tree from the first."""
    n = 10000
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(name="sx1", init={"seed": 1})
        c1 = await sf.client()
        for i in range(n):
            await c1.d.set(P(f"a.{i % 50}.{i}"), i)
        # Let server 1 retain the data.
        await anyio.sleep(0.5)

        # The joining server must complete its initial sync (not stall).
        sf.cfg.server.timeout.startup = 10
        with anyio.fail_after(11):
            s2 = await sf.server(name="sx2")
        assert s2 is not None

        # The full tree must be visible through the joining server.
        c2 = await sf.client()
        seen: set[str] = set()
        with anyio.fail_after(10):
            async with c2.d_walk(P("a")) as w:
                async for p, _d in w:
                    seen.add(str(p))
        assert len(seen) >= n, f"sync incomplete: saw {len(seen)} of {n}"
