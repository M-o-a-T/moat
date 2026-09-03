#!/usr/bin/env python3
"""
Python interop fixture: a simple MoaT RPC server that speaks the wire protocol.

Used by test/interop/interop.test.ts to verify TS↔Python wire compatibility.

Usage: python3 scripts/interop-server.py [--ws PORT | --tcp PORT | --stdio]

Protocol:
  - WebSocket: binary frames carry CBOR-encoded RPC messages
  - TCP: CBOR arrays streamed back-to-back (no length prefix)
  - stdio: CBOR arrays on stdin/stdout

Commands:
  - ping → "pong"
  - echo(*args) → args
  - add(a, b) → a + b
  - error_test → raises ValueError (forwarded as error)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path as FSPath

import asyncio

repo_root = FSPath(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from moat.lib.rpc import MsgHandler
from moat.lib.rpc.anyio import AioStream


class InteropHandler(MsgHandler):
    """Simple handler with a few commands for interop testing."""

    async def cmd_ping(self) -> str:
        """Reply with ``"pong"``."""
        return "pong"

    async def cmd_echo(self, *args):
        """Return the supplied arguments unchanged."""
        return args

    async def cmd_add(self, a: int, b: int) -> int:
        """Return the sum of *a* and *b*."""
        return a + b

    async def cmd_multiply(self, a: int, b: int) -> int:
        """Return the product of *a* and *b*."""
        return a * b

    async def cmd_error_test(self):
        """Raise a ``ValueError`` to exercise error forwarding."""
        raise ValueError("test error from Python")


async def run_stdio():
    """Run RPC over stdin/stdout (CBOR arrays, no framing)."""
    handler = InteropHandler()

    class StdioRW:
        async def read(self, n):
            return await asyncio.to_thread(sys.stdin.buffer.read, n)

        async def write(self, data):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

    stream = AioStream(handler, StdioRW())
    async with stream:
        await asyncio.sleep(999)  # keep running


async def run_tcp(port: int):
    """Run RPC over TCP."""
    handler = InteropHandler()

    async def handle_connection(reader, writer):
        rw = _TcpRW(reader, writer)
        stream = AioStream(handler, rw)
        try:
            async with stream:
                await asyncio.sleep(999)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: S110
                pass

    server = await asyncio.start_server(handle_connection, "localhost", port)
    print(f"Python TCP server listening on port {port}", file=sys.stderr)
    async with server:
        await server.serve_forever()


class _TcpRW:
    """Adapt asyncio StreamReader/StreamWriter to AioStream's interface."""

    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer

    async def read(self, n):
        return await self._reader.read(n)

    async def write(self, data):
        self._writer.write(data)
        await self._writer.drain()


async def run_ws(port: int):
    """Run RPC over WebSocket."""
    try:
        import websockets  # noqa:PLC0415
    except ImportError:
        print("websockets not installed; skipping WS mode", file=sys.stderr)
        return

    handler = InteropHandler()

    async def ws_handler(websocket):
        rw = _WsRW(websocket)
        stream = AioStream(handler, rw)
        try:
            async with stream:
                await asyncio.sleep(999)
        except Exception:  # noqa: S110
            pass

    async with websockets.serve(ws_handler, "localhost", port):
        print(f"Python WS server listening on port {port}", file=sys.stderr)
        await asyncio.Future()  # run forever


class _WsRW:
    """Adapt a websocket to AioStream's interface."""

    def __init__(self, websocket):
        self._ws = websocket

    async def read(self, _n):
        data = await self._ws.recv()
        if isinstance(data, bytes):
            return data
        return data.encode() if isinstance(data, str) else b""

    async def write(self, data):
        await self._ws.send(data)


def main():
    """Parse transports arguments and launch the chosen server."""
    parser = argparse.ArgumentParser(description="MoaT RPC interop server")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stdio", action="store_true", help="Use stdin/stdout")
    group.add_argument("--tcp", type=int, metavar="PORT", help="TCP port")
    group.add_argument("--ws", type=int, metavar="PORT", help="WebSocket port")
    args = parser.parse_args()

    if args.stdio:
        asyncio.run(run_stdio())
    elif args.tcp:
        asyncio.run(run_tcp(args.tcp))
    elif args.ws:
        asyncio.run(run_ws(args.ws))


if __name__ == "__main__":
    main()
