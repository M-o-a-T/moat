"""
A Link client survives cancellation until its context is left, so code
inside the context can still use it to clean up (moat-n84.32).
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.client import Link

pytestmark = pytest.mark.anyio


async def test_cleanup_after_cancel(cfg):
    "a shielded cleanup in a cancelled block can still talk to the server"
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as obs,
    ):
        done = False
        with anyio.CancelScope() as sc:
            async with sf.client_() as c:
                try:
                    sc.cancel()
                    await anyio.sleep(10)
                finally:
                    with anyio.CancelScope(shield=True), anyio.fail_after(5):
                        await c.d_set(P("test.cleanup"), 42, retain=True)
                        await c.i_sync()
                        done = True
        assert sc.cancelled_caught
        assert done
        await obs.i_sync()
        assert await obs.d_get(P("test.cleanup")) == 42


async def test_cancel_method(cfg):
    "Link.cancel() ends the block, and the context exits cleanly"
    async with Scaffold(cfg, use_servers=True) as sf, sf.server_(init={"Hello": "there!"}):
        cli = Link(sf.cfg, "C_cancel")
        with anyio.fail_after(5):
            async with cli:
                cli.cancel()
                await anyio.sleep(10)
