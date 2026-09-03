#!/usr/bin/env python3
"""
Python interop client: connects to a TS RPC server over TCP,
sends requests using the raw wire protocol, and reports results.

Captures the raw wire bytes (hex) for each exchange so the TS test
suite can assert byte-for-byte compatibility.

Usage:
  python3 scripts/interop-client.py --tcp HOST PORT

Outputs JSON to stdout:
  {"exchanges": [
    {"desc": "ping", "request_hex": "...", "response_hex": "...", "result": "pong"},
    ...
  ]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path as FSPath

import asyncio

repo_root = FSPath(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from moat.lib.codec.moat_cbor import Codec as MoatCborCodec


def i_f2wire(msg_id: int, flag: int) -> int:
    """Pack (id, flag) into the wire header integer."""
    if msg_id == 0:
        raise ValueError("id must not be 0")
    if msg_id > 0:
        msg_id -= 1
    return (msg_id << 2) | (flag & 3)


def wire2i_f(w: int) -> tuple[int, int]:
    """Decode a wire header integer into (id, flag)."""
    f = w & 3
    msg_id = w >> 2
    if msg_id >= 0:
        msg_id += 1
    return msg_id, f


async def send_and_receive(reader, writer, codec, msg_id, cmd, *args):
    """Send a single RPC call and wait for the response.

    Returns (request_hex, response_hex, decoded_response).
    """
    # Build the wire message: [header, [cmd], *args]
    header = i_f2wire(msg_id, 0)
    wire_msg = [header, [cmd]] + list(args)

    # Encode
    request_data = codec.encode(wire_msg)
    request_hex = request_data.hex()

    # Send
    writer.write(request_data)
    await writer.drain()

    # Receive response — read until we have a complete CBOR object
    recv_buf = bytearray()
    response_decoded = None

    while response_decoded is None:
        chunk = await reader.read(4096)
        if not chunk:
            raise EOFError("Connection closed")
        recv_buf.extend(chunk)

        # Try to decode
        codec2 = MoatCborCodec()
        codec2.feed(bytes(recv_buf))
        try:
            for msg in codec2:
                response_decoded = msg
                break
        except Exception:  # noqa: S110  incomplete data, wait for more bytes
            pass

    # Re-encode to get canonical hex
    response_hex = codec.encode(response_decoded).hex()

    return request_hex, response_hex, response_decoded


async def run_tcp_client(host: str, port: int):
    """Connect to a TS server, run 10+ test exchanges, output JSON."""
    codec = MoatCborCodec()

    # Representative test cases (>= 10)
    test_cases = [
        ("ping", [], "ping"),
        ("add", [3, 4], "add(3,4)"),
        ("echo", ["hello", 42], "echo(hello,42)"),
        ("add", [100, 200], "add(100,200)"),
        ("multiply", [6, 7], "multiply(6,7)"),
        ("echo", [True, None, "world"], "echo(True,None,world)"),
        ("add", [-5, 10], "add(-5,10)"),
        ("echo", [1.5], "echo(1.5)"),
        ("add", [0, 0], "add(0,0)"),
        ("echo", ["unicode_test"], "echo(unicode_test)"),
        ("add", [1, 1], "add(1,1)"),
        ("echo", [255], "echo(255)"),
    ]

    exchanges = []

    try:
        reader, writer = await asyncio.open_connection(host, port)
    except (ConnectionRefusedError, OSError) as e:
        print(json.dumps({"error": f"Connection failed: {e}", "exchanges": []}))
        return

    for idx, (cmd, args, desc) in enumerate(test_cases, start=1):
        msg_id = idx
        try:
            req_hex, resp_hex, decoded = await send_and_receive(
                reader, writer, codec, msg_id, cmd, *args
            )

            # Extract result from decoded response: [resp_header, *result_args]
            if isinstance(decoded, list) and len(decoded) >= 1:
                resp_header = decoded[0]
                _, resp_flag = wire2i_f(resp_header)
                result_args = decoded[1:]

                if resp_flag & 2:  # B_ERROR
                    result_repr = f"ERROR: {result_args}"
                else:
                    if len(result_args) == 1:
                        result_repr = repr(result_args[0])
                    elif len(result_args) == 0:
                        result_repr = "None"
                    else:
                        result_repr = repr(tuple(result_args))
            else:
                result_repr = repr(decoded)

            exchanges.append({
                "desc": desc,
                "request_hex": req_hex,
                "response_hex": resp_hex,
                "result": result_repr,
                "msg_id": msg_id,
            })

        except Exception as e:
            exchanges.append({
                "desc": desc,
                "error": str(e),
                "msg_id": msg_id,
            })

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: S110
        pass

    print(json.dumps({"exchanges": exchanges}))


def main():
    """Parse transport arguments and drive the interop exchanges."""
    parser = argparse.ArgumentParser(description="MoaT RPC interop client")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tcp", nargs=2, metavar=("HOST", "PORT"), help="TCP host and port")
    args = parser.parse_args()

    if args.tcp:
        host, port = args.tcp
        asyncio.run(run_tcp_client(host, int(port)))


if __name__ == "__main__":
    main()
