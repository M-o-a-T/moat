"host tests"

from __future__ import annotations

import anyio
import pytest

from moat.util import P, ungroup
from moat.lib.cmd.base import MsgHandler
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
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                # If the test fails here, most likely you're using the
                # system broker and have retained messages lying around.
                # TODO.
                async with announcing(c1, P("foo.bar"), value="C1") as s:
                    s.set()
                    evt.set()
                    await c1.i_sync()
                    await anyio.sleep(0.3)

            @tg.start_soon
            async def ann2():
                with anyio.fail_after(1.2):
                    await evt.wait()
                await anyio.sleep(0.2)
                with pytest.raises(ServiceSupplanted), ungroup:  # noqa:PT012
                    async with announcing(c2, P("foo.bar"), value="C2") as s:
                        s.set()
                        await anyio.sleep(0.2)

            with anyio.fail_after(1.0):
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
                        s.set()
                        await c1.i_sync()
                        evt.set()
                        with anyio.fail_after(1.4):
                            await evt2.wait()
                        raise AssertionError("This should not be reached")

            @tg.start_soon
            async def ann2():
                with anyio.fail_after(1.2):
                    await evt.wait()
                async with announcing(c2, P("foo.bar"), force=True) as s:
                    s.set()
                    await anyio.sleep(0.2)
                    evt2.set()
                    await anyio.sleep(0.2)

            with anyio.fail_after(1.0):
                await evt2.wait()
            await anyio.sleep(0.15)


@pytest.mark.anyio
async def test_call(cfg):
    "service call test"

    class CmdI(MsgHandler):
        async def cmd_yes(self, yeah):
            return yeah * 2

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        evt = anyio.Event()
        evt2 = anyio.Event()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                async with announcing(c1, P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()
            res = await c2.get_service(P("foo.bar"))
            d = await res.yes(22)
            assert d[0] == 44
            evt2.set()
