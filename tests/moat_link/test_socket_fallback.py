"""
A client whose Unix socket doesn't exist falls back to the announced servers.
"""

from __future__ import annotations

import pytest

from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("moat_tb", [False, True])
async def test_missing_socket(cfg, tmp_path, monkeypatch, moat_tb):
    """
    The configured socket is missing: connect via the server's announcement.

    With ``MOAT_TB`` set, `moat.util.ungroup` doesn't unwrap exception groups,
    so the ``FileNotFoundError`` arrives wrapped in a group.
    """
    if moat_tb:
        monkeypatch.setenv("MOAT_TB", "1")
    else:
        monkeypatch.delenv("MOAT_TB", raising=False)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")
        ccfg = dict(client=dict(path=str(tmp_path / "missing.sock")))
        async with sf.client_(cfg=ccfg) as c:
            await c.d_set(P("test.fallback"), 42)
            assert await c.d_get(P("test.fallback")) == 42
