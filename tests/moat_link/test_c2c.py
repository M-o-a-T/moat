"host tests"

from __future__ import annotations

import anyio
import pytest
import time

from moat.link._test import Scaffold
from moat.link.meta import MsgMeta
from moat.link.host import HostState, HostList
from moat.util import P


@pytest.mark.anyio()
async def test_simple(cfg):
    "simple client-to-client comm test"
    async with Scaffold(cfg, use_servers=False) as sf:
        s = await sf.server(init="Foo")
        # evt = await sf.tg.start(cl)

        c1 = await sf.client(name="Foom")
        c2 = await sf.client()

        @sf.tg.start_soon
        async def test():
            await anyio.sleep(1)
            sf.tg.cancel_scope.cancel()

        async with HostList(sf.cfg, c2) as br:
            async for h in br:
                print(h)
