"""
Connecting to a named server that isn't announced.
"""

from __future__ import annotations

import pytest

from moat.util import ungroup
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_unknown_server(cfg, monkeypatch):
    "The error names the server we waited for."
    monkeypatch.delenv("MOAT_TB", raising=False)

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")
        ccfg = dict(client=dict(name="no-such-server", init_timeout=0.5))
        with pytest.raises(TimeoutError, match=r"'no-such-server'.*Is it running"), ungroup:
            async with sf.client_(cfg=ccfg):
                pass
