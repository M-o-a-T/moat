"""
A client whose Unix socket doesn't exist falls back to the announced servers.
"""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_missing_socket(cfg, tmp_path, monkeypatch):
    """
    The configured socket is missing: connect via the server's announcement.
    """
    # With MOAT_TB set, errors are surfaced on purpose (wrapped in groups);
    # the fallback isn't expected to cope with that.
    monkeypatch.delenv("MOAT_TB", raising=False)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")
        ccfg = dict(client=dict(path=str(tmp_path / "missing.sock")))
        async with sf.client_(cfg=ccfg) as c:
            await c.d_set(P("test.fallback"), 42)
            # d_set goes to MQTT; wait until the server has it
            await c.i_sync()
            assert await c.d_get(P("test.fallback")) == 42
