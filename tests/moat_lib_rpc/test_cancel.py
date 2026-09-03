"""Tests for client-side cancellation of non-streaming RPC calls."""

from __future__ import annotations

import anyio
import pytest

from tests.moat_lib_rpc.scaffold import scaffold

from moat.lib.micro import CancelledError
from moat.lib.rpc import MsgHandler


@pytest.mark.anyio
async def test_cancel_nonstream():
    """Client cancels a slow non-streaming server command.

    The server handler task is cancelled (observable side-effect does
    not happen) and the interaction closes cleanly.
    """

    class EP(MsgHandler):
        done = False

        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            await anyio.sleep(999)
            EP.done = True  # pragma: no cover
            await msg.result("slow")

    async with scaffold(EP(), None) as (_a, b), anyio.create_task_group() as tg:

        async def caller():
            with pytest.raises(anyio.get_cancelled_exc_class()):
                await b.cmd("Test")

        tg.start_soon(caller)
        # Give the command time to reach the server, then cancel.
        await anyio.sleep(0.05)
        tg.cancel_scope.cancel()

    assert not EP.done, "Handler should have been cancelled"


@pytest.mark.anyio
async def test_cancel_nonstream_side_effect():
    """Cancel a non-streaming call and verify the side effect does NOT happen."""

    started = anyio.Event()
    cancelled = False

    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):  # noqa: ARG004
            rcmd  # noqa:B018
            nonlocal cancelled
            started.set()
            try:
                await anyio.sleep(999)
            except anyio.get_cancelled_exc_class():
                cancelled = True
                raise

    async with scaffold(EP(), None) as (_a, b), anyio.create_task_group() as tg:

        async def caller():
            with pytest.raises(anyio.get_cancelled_exc_class()):
                await b.cmd("Test")

        tg.start_soon(caller)
        await started.wait()
        await anyio.sleep(0.05)
        tg.cancel_scope.cancel()

    assert cancelled, "Handler should have been cancelled by the client"


@pytest.mark.anyio
async def test_cancel_after_reply():
    """Client cancels after the server already replied (race).

    The server discards the cancel (no open command); no error.
    """

    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            await msg.result("fast")

    async with scaffold(EP(), None) as (_a, b):
        # Complete the call normally first.
        res = await b.cmd("Test")
        assert tuple(res.args) == ("fast",)


@pytest.mark.anyio
async def test_server_cancel_nonstream():
    """Server-initiated cancel of a non-streaming call still works (regression)."""

    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):  # noqa: ARG004
            rcmd  # noqa:B018
            raise CancelledError

    async with scaffold(EP(), None) as (_a, b):
        with pytest.raises(CancelledError):
            await b.cmd("Test")


@pytest.mark.anyio
async def test_cancel_nonstream_concurrent():
    """Multiple concurrent non-streaming calls; cancel one, others succeed."""

    class EP(MsgHandler):
        @staticmethod
        async def handle(msg, rcmd):
            rcmd  # noqa:B018
            if msg.args[0] == 0:
                await anyio.sleep(999)
                await msg.result("slow")  # pragma: no cover
            else:
                await anyio.sleep(0.01)
                await msg.result(f"ok{msg.args[0]}")

    results: list[str] = []

    async with scaffold(EP(), None) as (_a, b), anyio.create_task_group() as tg:

        async def caller(idx):
            if idx == 0:
                with pytest.raises(anyio.get_cancelled_exc_class()):
                    await b.cmd("Test", idx)
            else:
                (res,) = await b.cmd("Test", idx)
                results.append(res)

        tg.start_soon(caller, 0)
        await anyio.sleep(0.05)
        tg.start_soon(caller, 1)
        tg.start_soon(caller, 2)
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()

    assert sorted(results) == ["ok1", "ok2"]
