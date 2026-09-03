"""Tests for ServiceSender self-refresh on destination restart."""

from __future__ import annotations

import anyio
import pytest

from moat.lib.path import P
from moat.lib.rpc import MsgHandler
from moat.link._test import Scaffold


@pytest.mark.anyio
async def test_service_call_basic(cfg):
    """Verify that get_service still works for a basic call."""

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
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()
            res = await c2.get_service(P("foo.bar"))
            d = await res.yes(22)
            assert d[0] == 44
            evt2.set()


@pytest.mark.anyio
async def test_service_restart(cfg):
    """Verify that ServiceSender re-resolves after a service restart."""

    class CmdI(MsgHandler):
        async def cmd_yes(self, yeah):
            return yeah * 3

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")

        c1 = await sf.client()
        c2 = await sf.client()
        evt = anyio.Event()
        evt2 = anyio.Event()
        evt3 = anyio.Event()
        async with anyio.create_task_group() as tg:

            @tg.start_soon
            async def ann1():
                # First announcement
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()

            # Get the service sender
            res = await c2.get_service(P("foo.bar"))
            d = await res.yes(10)
            assert d[0] == 30

            # Terminate the first service
            evt2.set()
            await anyio.sleep(0.3)

            # Restart with a new service
            @tg.start_soon
            async def ann2():
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt3.set()
                    await anyio.sleep(0.5)

            await evt3.wait()
            await c1.i_sync()
            await anyio.sleep(0.3)

            # The ServiceSender should have re-resolved automatically
            d = await res.yes(10)
            assert d[0] == 30


@pytest.mark.anyio
async def test_service_terminate(cfg):
    """Verify that ServiceSender raises when the service is terminated."""

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
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()
            res = await c2.get_service(P("foo.bar"))
            d = await res.yes(22)
            assert d[0] == 44

            # Terminate the service
            evt2.set()
            await anyio.sleep(0.3)

            # The ServiceSender should raise because the service is gone
            with pytest.raises(RuntimeError, match="Service not available"):
                await res.yes(22)


@pytest.mark.anyio
async def test_service_sender_repr(cfg):
    """Verify that ServiceSender has a useful repr."""

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
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()
            res = await c2.get_service(P("foo.bar"))
            r = repr(res)
            assert "ServiceSender" in r
            d = await res.yes(22)
            assert d[0] == 44
            evt2.set()


@pytest.mark.anyio
async def test_service_call_with_list(cfg):
    """Verify that ServiceSender.__call__ separates _list from **kw.

    ``_list`` must reach the Caller as a separate parameter, not be
    packed into the command kwargs that travel over the wire.
    """

    class CmdI(MsgHandler):
        async def cmd(self, yeah):  # root command
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
                async with c1.announcing(P("foo.bar"), service=CmdI(), host=False) as s:
                    s.set()
                    evt.set()
                    await evt2.wait()

            await evt.wait()
            await c1.i_sync()
            res = await c2.get_service(P("foo.bar"))

            # Direct __call__ delegates to SubMsgSender.__call__,
            # which creates a Caller with the full service path as cmd.
            # _list must be separated from kwargs, not packed into them.
            caller = res(22, _list=True)
            assert caller._list is True  # noqa:SLF001
            _, _, kw = caller.data
            assert "_list" not in kw, "_list leaked into command kwargs"

            # The call should reach the service's root command.
            d = await caller
            assert d[0] == 44

            evt2.set()
