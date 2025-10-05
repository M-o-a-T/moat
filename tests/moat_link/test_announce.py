"host tests"

from __future__ import annotations

import anyio
import gc
import pytest

from moat.util import P, ungroup
from moat.link._test import Scaffold
from moat.link.announce import announcing
from moat.link.exceptions import ServiceNotStarted, ServiceSupplanted


@pytest.mark.anyio
async def test_basic(cfg):
    "host monitoring test"

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                async with announcing(c1, P("foo.bar")) as s:
                    await s.announce()
                    evt.set()

            @tg.start_soon
            async def ann2():
                await evt.wait()
                with pytest.raises(ServiceSupplanted), ungroup:  # noqa:PT012
                    async with announcing(c2, P("foo.bar")) as s:
                        await s.announce()
                        await anyio.sleep(0.2)

            await evt.wait()
            await anyio.sleep(0.1)


@pytest.mark.anyio
async def test_force(cfg):
    "host monitoring test with force"

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        evt = anyio.Event()
        evt2 = anyio.Event()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                with pytest.raises(ServiceSupplanted), ungroup:  # noqa:PT012
                    async with announcing(c1, P("foo.bar")) as s:
                        await s.announce()
                        evt.set()
                        await evt2.wait()
                        raise AssertionError("This should not be reached")

            @tg.start_soon
            async def ann2():
                await evt.wait()
                async with announcing(c2, P("foo.bar"), force=True) as s:
                    await s.announce()
                    await anyio.sleep(0.1)
                    evt2.set()

            await evt2.wait()
            await anyio.sleep(0.1)


@pytest.mark.anyio
async def test_warning(cfg):
    "host monitoring test with warning"

    async with Scaffold(cfg, use_servers=True) as sf:
        with pytest.warns(ServiceNotStarted, match="freed before"):  # noqa:PT031
            await sf.server(init="TEST")

            c1 = await sf.client()

            @sf.tg.start_soon
            async def ann1():
                async with announcing(c1, P("foo.bar")):
                    await anyio.sleep(0.1)
                    gc.collect()

            await anyio.sleep(0.2)
