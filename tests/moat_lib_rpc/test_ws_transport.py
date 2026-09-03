"""
Websocket transport tests.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.rpc.conn.ws import WsIter
from moat.lib.stream.ws import SingleWsBlk, WsLink

pytestmark = pytest.mark.anyio


async def test_ws_transport():
    "binary blocks and text console share one websocket transport"
    got = {}

    async with WsIter("127.0.0.1", 0, "/rpc") as conns, anyio.create_task_group() as tg:
        port = conns.port

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


async def _ws_subprobe(conns, got):
    """Accept one WS connection and record its negotiated subprotocol."""
    conn = await anext(conns)
    assert isinstance(conn, SingleWsBlk)
    async with conn:
        got["server_subprotocol"] = conn.subprotocol


async def test_ws_subprotocol_match():
    "client and server agree on a subprotocol"
    got = {}

    async with (
        WsIter("127.0.0.1", 0, "/rpc", subprotocols=["moat-rpc"]) as conns,
        anyio.create_task_group() as tg,
    ):
        port = conns.port

        tg.start_soon(_ws_subprobe, conns, got)
        async with WsLink(
            f"ws://127.0.0.1:{port}/rpc",
            retry={"delay": 0.01, "attempts": 10, "timeout": 5},
            subprotocols=["moat-rpc"],
        ) as client:
            got["client_subprotocol"] = client.subprotocol

        conns.tg.cancel_scope.cancel()

    assert got == {"server_subprotocol": "moat-rpc", "client_subprotocol": "moat-rpc"}


async def test_ws_subprotocol_select_first():
    "server picks the first client-offered subprotocol it recognises"
    got = {}

    async with (
        WsIter("127.0.0.1", 0, "/rpc", subprotocols=["proto-b", "proto-a"]) as conns,
        anyio.create_task_group() as tg,
    ):
        port = conns.port

        tg.start_soon(_ws_subprobe, conns, got)
        # Client offers proto-a first, then proto-b; server prefers proto-b.
        async with WsLink(
            f"ws://127.0.0.1:{port}/rpc",
            retry={"delay": 0.01, "attempts": 10, "timeout": 5},
            subprotocols=["proto-a", "proto-b"],
        ) as client:
            got["client_subprotocol"] = client.subprotocol

        conns.tg.cancel_scope.cancel()

    assert got == {
        "server_subprotocol": "proto-a",
        "client_subprotocol": "proto-a",
    }


async def test_ws_no_subprotocol():
    "no subprotocol negotiation when neither side offers any"
    got = {}

    async with WsIter("127.0.0.1", 0, "/rpc") as conns, anyio.create_task_group() as tg:
        port = conns.port

        tg.start_soon(_ws_subprobe, conns, got)
        async with WsLink(
            f"ws://127.0.0.1:{port}/rpc",
            retry={"delay": 0.01, "attempts": 10, "timeout": 5},
        ) as client:
            got["client_subprotocol"] = client.subprotocol

        conns.tg.cancel_scope.cancel()

    assert got == {"server_subprotocol": None, "client_subprotocol": None}
