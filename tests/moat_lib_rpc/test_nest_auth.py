"""Tests for authenticated CmdStream (rpc_on_rpc with auth)."""

from __future__ import annotations

import anyio
import pytest

from moat.util import attrdict
from moat.lib.rpc import MsgHandler, MsgSender, rpc_on_rpc

# Auth config for the "test" auth method.  ``ok: true`` means accept.
AUTH_CFG_OK = attrdict(
    auth=attrdict(
        modes=[attrdict(mode="test")],
        ok=True,
        test=attrdict(ok=True),
    )
)

# Auth config that denies.
AUTH_CFG_DENY = attrdict(
    auth=attrdict(
        modes=[attrdict(mode="test")],
        ok=False,
        test=attrdict(ok=False),
    )
)


class EchoCmd(MsgHandler):
    """Simple handler that doubles the first argument."""

    async def cmd_echo(self, m):
        """Double the input."""
        return m * 2


@pytest.mark.anyio
async def test_nested_auth_basic():
    """Both sides authenticate, then exchange commands."""
    evt1 = anyio.Event()
    evt2 = anyio.Event()

    class EP(MsgHandler):
        async def stream_Test(self, msg):
            async with (
                msg.stream(),
                rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_OK, is_server=True, debug="B") as cmdo,
            ):
                assert cmdo.auth is not None
                (res,) = await MsgSender(cmdo).cmd("echo", "srv")
                assert res == "srvsrv"
                evt1.set()
                await evt2.wait()

    ep = EP()
    ms = MsgSender(ep)

    async with (
        ms.cmd("Test").stream() as msg,
        rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_OK, debug="A") as cmdo,
    ):
        assert cmdo.auth is not None
        (res,) = await MsgSender(cmdo).cmd("echo", "cli")
        assert res == "clicli"
        await evt1.wait()
        evt2.set()


@pytest.mark.anyio
async def test_nested_auth_populates_auth_data():
    """Verify that cmdo.auth contains a SubAuth after auth completes."""
    evt = anyio.Event()

    class EP(MsgHandler):
        async def stream_Test(self, msg):
            async with (
                msg.stream(),
                rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_OK, is_server=True, debug="B") as cmdo,
            ):
                assert cmdo.auth is not None
                assert hasattr(cmdo.auth, "name")
                evt.set()
                await anyio.sleep(0.5)

    ep = EP()
    ms = MsgSender(ep)

    async with (
        ms.cmd("Test").stream() as msg,
        rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_OK, debug="A") as cmdo,
    ):
        assert cmdo.auth is not None
        assert hasattr(cmdo.auth, "name")
        await evt.wait()


@pytest.mark.anyio
async def test_nested_auth_denied():
    """Auth denial should raise an exception on both sides."""
    evt = anyio.Event()

    class EP(MsgHandler):
        async def stream_Test(self, msg):
            try:
                async with (
                    msg.stream(),
                    rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_DENY, is_server=True, debug="B"),
                ):
                    pass
            except Exception:
                evt.set()
                return
            raise AssertionError("Should have been denied")

    ep = EP()
    ms = MsgSender(ep)

    with pytest.raises(ExceptionGroup):
        async with (
            ms.cmd("Test").stream() as msg,
            rpc_on_rpc(EchoCmd(), msg, auth=AUTH_CFG_DENY, debug="A"),
        ):
            pass

    with anyio.fail_after(2):
        await evt.wait()


@pytest.mark.anyio
async def test_nested_no_auth_works_without_auth_param():
    """Ensure rpc_on_rpc still works without the auth parameter."""
    evt1 = anyio.Event()
    evt2 = anyio.Event()

    class EP(MsgHandler):
        async def stream_Test(self, msg):
            async with msg.stream(), rpc_on_rpc(EchoCmd(), msg, debug="B") as cmdo:
                assert cmdo.auth is None
                (res,) = await MsgSender(cmdo).cmd("echo", "srv")
                assert res == "srvsrv"
                evt1.set()
                await evt2.wait()

    ep = EP()
    ms = MsgSender(ep)

    async with ms.cmd("Test").stream() as msg, rpc_on_rpc(EchoCmd(), msg, debug="A") as cmdo:
        assert cmdo.auth is None
        (res,) = await MsgSender(cmdo).cmd("echo", "cli")
        assert res == "clicli"
        await evt1.wait()
        evt2.set()
