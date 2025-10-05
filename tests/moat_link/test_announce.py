"host tests"

from __future__ import annotations

import anyio
import pytest
import sys

from moat.util import P, ungroup
from moat.link._test import Scaffold
from moat.link.announce import announcing
from moat.link.exceptions import ServiceSupplanted


@pytest.mark.anyio
async def test_basic(cfg):
    "host monitoring test"

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                async with announcing(c1, P("foo.bar")) as s:
                    s.set()
                    await anyio.sleep(0.2)

            @tg.start_soon
            async def ann2():
                await anyio.sleep(0.1)
                with pytest.raises(ServiceSupplanted), ungroup:  # noqa:PT012
                    async with announcing(c2, P("foo.bar")) as s:
                        s.set()
                        await anyio.sleep(0.2)

            await anyio.sleep(0.3)
        print("A", file=sys.stderr)


@pytest.mark.anyio
async def test_force(cfg):
    "host monitoring test with force"

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                with pytest.raises(ServiceSupplanted), ungroup:  # noqa:PT012
                    async with announcing(c1, P("foo.bar")) as s:
                        s.set()
                        await anyio.sleep(0.2)

            @tg.start_soon
            async def ann2():
                await anyio.sleep(0.1)
                async with announcing(c2, P("foo.bar"), force=True) as s:
                    s.set()
                    await anyio.sleep(0.2)

            await anyio.sleep(0.3)
        print("A", file=sys.stderr)
