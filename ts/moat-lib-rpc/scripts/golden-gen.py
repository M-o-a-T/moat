#!/usr/bin/env python3
"""
Generate golden CBOR vectors from Python moat.lib.rpc.

These byte vectors pin the wire protocol so TS↔Python drift is caught.
Regenerate with: python3 scripts/golden-gen.py

Output: test/fixtures/golden.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path as FSPath

# Ensure we can import moat from the repo
repo_root = FSPath(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

from moat.lib.codec.moat_cbor import Codec as MoatCborCodec
from moat.lib.rpc.stream.base import i_f2wire, wire2i_f
from moat.lib.rpc.const import (
    B_STREAM, B_ERROR, B_WARNING, B_WARNING_INTERNAL,
    E_UNSPEC, E_NO_STREAM, E_CANCEL, E_NO_CMDS, E_SKIP, E_ERROR, E_NO_CMD,
)
from moat.lib.rpc.errors import StreamError
from moat.lib.path import Path
from moat.lib.proxy import as_proxy


def hexlify(data: bytes) -> str:
    return data.hex()


def encode_cbor(val) -> str:
    codec = MoatCborCodec()
    return hexlify(codec.encode(val))


def main():
    vectors = {}

    # --- Header packing ---
    vectors["header"] = {
        "id1_flag0": i_f2wire(1, 0),        # 0
        "id1_flag1": i_f2wire(1, 1),        # 1
        "id2_flag0": i_f2wire(2, 0),        # 4
        "id_neg1_flag0": i_f2wire(-1, 0),   # -4
        "id_neg1_flag2": i_f2wire(-1, 2),   # -2
        "decode_0": list(wire2i_f(0)),       # [1, 0]
        "decode_4": list(wire2i_f(4)),       # [2, 0]
        "decode_neg4": list(wire2i_f(-4)),   # [-1, 0]
        "decode_neg2": list(wire2i_f(-2)),   # [-1, 2]
    }

    # --- Simple call message: [header, cmd_path, *args] ---
    # Originator id=1, flag=0 → wire=0, cmd=["ping"]
    vectors["simple_call"] = {
        "wire": encode_cbor([0, ["ping"]]),
        "expected": [0, ["ping"]],
    }

    # --- Reply message: responder uses id=-1 (flipped), flag=0 → wire=-4 ---
    vectors["simple_reply"] = {
        "wire": encode_cbor([-4, ["pong"]]),
        "expected": [-4, ["pong"]],
    }

    # --- Error reply: id=-1, flag=2 (B_ERROR) → wire=-2 ---
    vectors["error_reply"] = {
        "wire": encode_cbor([-2, [-3]]),  # E_CANCEL = -3
        "expected": [-2, [-3]],
    }

    # --- Call with args ---
    vectors["call_with_args"] = {
        "wire": encode_cbor([0, ["echo"], 42, "hello"]),
        "expected": [0, ["echo"], 42, "hello"],
    }

    # --- Call with kwargs (trailing map) ---
    vectors["call_with_kwargs"] = {
        "wire": encode_cbor([0, ["cmd"], {"key": "value"}]),
        "expected": [0, ["cmd"], {"key": "value"}],
    }

    # --- Path tag 39 ---
    vectors["path_tag39"] = {
        "wire": encode_cbor(Path.build(("foo", "bar"))),
        "note": "Path values are tagged with 39",
    }

    # --- Set tag 258 ---
    vectors["set_tag258"] = {
        "wire": encode_cbor({1, 2, 3}),
        "note": "Set is tagged with 258",
    }

    # --- Date tag 1 (epoch seconds) ---
    import datetime
    dt = datetime.datetime(2024, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
    vectors["date_tag1"] = {
        "wire": encode_cbor(dt),
        "note": "Date is tagged with 1 (epoch seconds)",
    }

    # --- Float widths (shortest-lossless) ---
    vectors["float_1_5"] = {"wire": encode_cbor(1.5)}
    vectors["float_0_1"] = {"wire": encode_cbor(0.1)}

    # --- Error codes ---
    vectors["error_codes"] = {
        "E_UNSPEC": E_UNSPEC,
        "E_NO_STREAM": E_NO_STREAM,
        "E_CANCEL": E_CANCEL,
        "E_NO_CMDS": E_NO_CMDS,
        "E_SKIP": E_SKIP,
        "E_ERROR": E_ERROR,
        "E_NO_CMD": E_NO_CMD,
    }

    # --- Unknown command: KeyError marshalled as _rErr ---
    # Python's handle() raises KeyError which is marshalled as tag 27 ["_rErr", "KeyError", ...]
    vectors["keyerror_marshall"] = {
        "note": "Unknown commands raise KeyError, marshalled as tag 27 [_rErr, KeyError, ...]",
    }

    # --- Boolean encoding (must be CBOR bool, not int 0/1) ---
    vectors["bool_true"] = {"wire": encode_cbor(True)}
    vectors["bool_false"] = {"wire": encode_cbor(False)}

    # --- Null and undefined ---
    vectors["null"] = {"wire": encode_cbor(None)}
    vectors["undefined"] = {"wire": encode_cbor(...)}  # Ellipsis → undefined

    # --- Bytes vs text ---
    vectors["bytes"] = {"wire": encode_cbor(b"\x01\x02\x03")}
    vectors["text"] = {"wire": encode_cbor("hello")}

    # Write output
    out_dir = FSPath(__file__).resolve().parent.parent / "test" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "golden.json"

    with open(out_path, "w") as f:
        json.dump(vectors, f, indent=2, default=str)

    print(f"Golden vectors written to {out_path}")
    print(f"  {len(vectors)} vector categories")


if __name__ == "__main__":
    main()
