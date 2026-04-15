"""
Websocket transport tests.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.rpc.conn.ws import WsIter
from moat.lib.stream.ws import WsLink

pytestmark = pytest.mark.anyio


async def test_ws_transport(free_tcp_port):
    "binary blocks and text console share one websocket transport"
    got = {}
    port = free_tcp_port

    async with WsIter("127.0.0.1", port, "/rpc") as conns, anyio.create_task_group() as tg:

        async def server():
            conn = await anext(conns)
            async with conn:
                got["in_b"] = await conn.rcv()
                await conn.snd(b"srv-b")
                b = bytearray(16)
                n = await conn.crd(b)
                got["in_c"] = bytes(b[:n])
                await conn.cwr(b"srv-console")

        tg.start_soon(server)
        async with WsLink(
            f"ws://127.0.0.1:{port}/rpc",
            retry={"delay": 0.01, "attempts": 10, "timeout": 5},
        ) as client:
            await client.snd(b"cli-b")
            assert await client.rcv() == b"srv-b"
            await client.cwr(b"cli-console")
            b = bytearray(4)
            n = await client.crd(b)
            assert bytes(b[:n]) == b"srv-"
            n = await client.crd(b)
            assert bytes(b[:n]) == b"cons"
            b = bytearray(8)
            n = await client.crd(b)
            assert bytes(b[:n]) == b"ole"

        # BaseConnIter is a long-running listener; stop it explicitly.
        conns.tg.cancel_scope.cancel()

    assert got == {"in_b": b"cli-b", "in_c": b"cli-console"}
