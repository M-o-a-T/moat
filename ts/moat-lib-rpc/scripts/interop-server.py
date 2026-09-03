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

from moat.lib.codec.moat_cbor import Codec as MoatCborCodec
from moat.lib.rpc import MsgHandler
from moat.lib.rpc.stream.base import HandlerStream


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

    async def cmd_error_test(self):
        """Raise a ``ValueError`` to exercise error forwarding."""
        raise ValueError("test error from Python")


async def run_stdio():
    """Run RPC over stdin/stdout (CBOR arrays, no framing)."""

    codec = MoatCborCodec()
    handler = InteropHandler()

    # Create a HandlerStream that reads from stdin and writes to stdout
    class StdioStream(HandlerStream):
        async def read_stream(self):
            while True:
                data = await asyncio.to_thread(sys.stdin.buffer.read, 4096)
                if not data:
                    break
                # Decode all complete CBOR objects from the buffer
                # (Simplified: assumes one message per read for phase 1)
                try:
                    msg = codec.decode(data)
                    if isinstance(msg, list):
                        await self.msg_in(msg)
                except Exception:  # noqa: S110  tolerate malformed frames
                    pass

        async def write_stream(self):
            while True:
                try:
                    msg = await self.msg_out()
                except EOFError:
                    break
                data = codec.encode(msg)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

    async with StdioStream(handler):
        await asyncio.sleep(999)  # keep running


async def run_tcp(port: int):
    """Run RPC over TCP."""

    codec = MoatCborCodec()
    handler = InteropHandler()

    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, handler, codec),
        "localhost",
        port,
    )
    print(f"Python TCP server listening on port {port}", file=sys.stderr)
    async with server:
        await server.serve_forever()


async def handle_connection(reader, writer, handler, codec):
    """Handle a single TCP connection."""

    class TcpStream(HandlerStream):
        async def read_stream(self):
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                try:
                    msg = codec.decode(data)
                    if isinstance(msg, list):
                        await self.msg_in(msg)
                except Exception:  # noqa: S110  tolerate malformed frames
                    pass

        async def write_stream(self):
            while True:
                try:
                    msg = await self.msg_out()
                except EOFError:
                    break
                data = codec.encode(msg)
                writer.write(data)
                await writer.drain()

    async with TcpStream(handler):
        await asyncio.sleep(999)


async def run_ws(port: int):
    """Run RPC over WebSocket."""
    try:
        import websockets  # noqa:PLC0415
    except ImportError:
        print("websockets not installed; skipping WS mode", file=sys.stderr)
        return

    codec = MoatCborCodec()
    handler = InteropHandler()

    async def ws_handler(websocket):
        class WsStream(HandlerStream):
            async def read_stream(self):
                async for data in websocket:
                    if isinstance(data, bytes):
                        msg = codec.decode(data)
                        if isinstance(msg, list):
                            await self.msg_in(msg)

            async def write_stream(self):
                while True:
                    try:
                        msg = await self.msg_out()
                    except EOFError:
                        break
                    data = codec.encode(msg)
                    await websocket.send(data)

        async with WsStream(handler):
            await asyncio.sleep(999)

    async with websockets.serve(ws_handler, "localhost", port):
        print(f"Python WS server listening on port {port}", file=sys.stderr)
        await asyncio.Future()  # run forever


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
