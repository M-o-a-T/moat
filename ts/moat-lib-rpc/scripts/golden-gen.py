#!/usr/bin/env python3
"""
Generate golden CBOR vectors from Python moat.lib.rpc.

These byte vectors pin the wire protocol so TS↔Python drift is caught.
Regenerate with: python3 scripts/golden-gen.py

Output: test/fixtures/golden.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path as FSPath

# Ensure we can import moat from the repo
repo_root = FSPath(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

from moat.lib.codec.moat_cbor import Codec as MoatCborCodec
from moat.lib.path import Path
from moat.lib.rpc.const import (
    E_CANCEL,
    E_ERROR,
    E_MUST_STREAM,
    E_NO_CMD,
    E_NO_CMDS,
    E_NO_STREAM,
    E_SKIP,
    E_UNSPEC,
)
from moat.lib.rpc.errors import StreamError
from moat.lib.rpc.stream.base import i_f2wire, wire2i_f


def hexlify(data: bytes) -> str:
    """Convert raw bytes to a lowercase hex string."""
    return data.hex()


def encode_cbor(val) -> str:
    """Encode *val* with MoaT-CBOR and return it hex-encoded."""
    codec = MoatCborCodec()
    return hexlify(codec.encode(val))


def main():
    """Build the golden-vector dictionary and write it to the fixtures file."""
    vectors = {}

    # === Section 1: Header packing ===
    hdr = {}
    # All flag × id combinations
    for flag in [0, 1, 2, 3]:
        for id_val in [1, 2, 3, -1, -2]:
            hdr[f"id{id_val}_flag{flag}"] = i_f2wire(id_val, flag)
    # Decode round-trips
    hdr["decode_0"] = list(wire2i_f(0))  # [1, 0]
    hdr["decode_4"] = list(wire2i_f(4))  # [2, 0]
    hdr["decode_neg4"] = list(wire2i_f(-4))  # [-1, 0]
    hdr["decode_neg2"] = list(wire2i_f(-2))  # [-1, 2]
    hdr["decode_1"] = list(wire2i_f(1))  # [1, 1]
    hdr["decode_3"] = list(wire2i_f(3))  # [1, 3]
    # Large id round-trip
    big_id = 0x20000000  # 2^29
    hdr["big_id_wire"] = i_f2wire(big_id, 0)
    hdr["big_id_decode"] = list(wire2i_f(hdr["big_id_wire"]))
    vectors["header"] = hdr

    # === Section 2: Request messages ===
    req = {
        "simple": {
            "wire": encode_cbor([0, ["ping"]]),
            "expected": [0, ["ping"]],
        },
        "with_args": {
            "wire": encode_cbor([0, ["echo"], 42, "hello"]),
            "expected": [0, ["echo"], 42, "hello"],
        },
        "with_kwargs": {
            "wire": encode_cbor([0, ["cmd"], {"key": "value"}]),
            "expected": [0, ["cmd"], {"key": "value"}],
        },
        "empty_cmd": {
            "wire": encode_cbor([0, []]),
            "expected": [0, []],
        },
        "multi_id": {
            "wire": encode_cbor([4, ["test"]]),
            "expected": [4, ["test"]],
        },
    }
    vectors["requests"] = req

    # === Section 3: Response messages ===
    resp = {
        "simple": {
            "wire": encode_cbor([-4, ["pong"]]),
            "expected": [-4, ["pong"]],
        },
        "none_result": {
            "wire": encode_cbor([-4, [None]]),
            "expected": [-4, [None]],
        },
        "multi": {
            "wire": encode_cbor([-4, [1, 2, 3]]),
            "expected": [-4, [1, 2, 3]],
        },
        "with_kwargs": {
            "wire": encode_cbor([-4, ["ok"], {"status": "done"}]),
            "expected": [-4, ["ok"], {"status": "done"}],
        },
    }
    vectors["responses"] = resp

    # === Section 4: Error messages ===
    errs = {
        "cancel": {
            "wire": encode_cbor([-2, [-3]]),
            "expected": [-2, [-3]],
            "code": E_CANCEL,
        },
        "no_stream": {
            "wire": encode_cbor([-2, [-2]]),
            "expected": [-2, [-2]],
            "code": E_NO_STREAM,
        },
        "generic": {
            "wire": encode_cbor([-2, [-7]]),
            "expected": [-2, [-7]],
            "code": E_ERROR,
        },
        "unspec": {
            "wire": encode_cbor([-2, [-1]]),
            "expected": [-2, [-1]],
            "code": E_UNSPEC,
        },
        "no_cmds": {
            "wire": encode_cbor([-2, [-4]]),
            "expected": [-2, [-4]],
            "code": E_NO_CMDS,
        },
        "skip": {
            "wire": encode_cbor([-2, [-5]]),
            "expected": [-2, [-5]],
            "code": E_SKIP,
        },
        "must_stream": {
            "wire": encode_cbor([-2, [-6]]),
            "expected": [-2, [-6]],
            "code": E_MUST_STREAM,
        },
        "no_cmd": {
            "wire": encode_cbor([-2, [-11]]),
            "expected": [-2, [-11]],
            "code": E_NO_CMD,
        },
        "flow_positive": {
            "wire": encode_cbor([-2, [42]]),
            "expected": [-2, [42]],
            "note": "Positive int = Flow(n), not an error",
        },
    }
    vectors["errors"] = errs

    # === Section 5: Warning messages (flag 3) ===
    warns = {
        "flow_control_int": {
            "wire": encode_cbor([-3, [42]]),
            "note": "Flag 3 + single int → B_WARNING_INTERNAL (flow control)",
        },
        "user_warning_with_kw": {
            "wire": encode_cbor([-3, [42, {}]]),
            "note": "User warning with empty kw to disambiguate from flow control",
        },
    }
    vectors["warnings"] = warns

    # === Section 6: Stream messages (flag 1) ===
    streams = {
        "data_item": {
            "wire": encode_cbor([1, [42]]),
            "note": "Stream data: id=1, flag=1 (B_STREAM)",
        },
        "stream_final": {
            "wire": encode_cbor([0, [42]]),
            "note": "Final message: id=1, flag=0",
        },
    }
    vectors["streams"] = streams

    # === Section 7: CBOR tags ===
    tags = {
        "path_simple": {
            "wire": encode_cbor(Path.build(("foo", "bar"))),
            "note": "Path values tagged with 39",
        },
        "path_empty": {
            "wire": encode_cbor(Path.build(())),
            "note": "Empty path tagged with 39",
        },
        "path_nested": {
            "wire": encode_cbor(Path.build(("a", "b", "c", "d"))),
            "note": "Nested path tagged with 39",
        },
        "set_empty": {
            "wire": encode_cbor(set()),
            "note": "Empty Set tagged with 258",
        },
        "set_ints": {
            "wire": encode_cbor({1, 2, 3}),
            "note": "Set of ints tagged with 258",
        },
    }
    vectors["tags"] = tags

    # === Section 8: Primitive values ===
    prims = {
        "bool_true": {"wire": encode_cbor(True)},
        "bool_false": {"wire": encode_cbor(False)},
        "null": {"wire": encode_cbor(None)},
        "undefined": {"wire": encode_cbor(...)},  # Ellipsis → undefined
        "empty_bytes": {"wire": encode_cbor(b"")},
        "bytes_123": {"wire": encode_cbor(b"\x01\x02\x03")},
        "text_hello": {"wire": encode_cbor("hello")},
        "int_pos_small": {"wire": encode_cbor(1)},
        "int_neg_small": {"wire": encode_cbor(-1)},
        "int_zero": {"wire": encode_cbor(0)},
        "int_large": {"wire": encode_cbor(1000000)},
        "float_1_5": {"wire": encode_cbor(1.5)},
        "float_0_1": {"wire": encode_cbor(0.1)},
    }
    vectors["primitives"] = prims

    # === Section 9: Error codes ===
    vectors["error_codes"] = {
        "E_UNSPEC": E_UNSPEC,
        "E_NO_STREAM": E_NO_STREAM,
        "E_CANCEL": E_CANCEL,
        "E_NO_CMDS": E_NO_CMDS,
        "E_SKIP": E_SKIP,
        "E_MUST_STREAM": E_MUST_STREAM,
        "E_ERROR": E_ERROR,
        "E_NO_CMD": E_NO_CMD,
    }

    # === Section 10: Error marshalling ===
    marshal = {}
    # KeyError marshalled as tag 27 ["_rErr", "KeyError", ...]
    try:
        raise KeyError("unknown_cmd")
    except KeyError as e:
        marshal["keyerror"] = {"wire": encode_cbor(e)}
    # ValueError marshalled
    try:
        raise ValueError("test error")
    except ValueError as e:
        marshal["valueerror"] = {"wire": encode_cbor(e)}
    # StreamError (registered proxy) → tag 32769
    try:
        raise NoStreamError
    except Exception as e:
        marshal["streamerror"] = {"wire": encode_cbor(e)}

    marshal["note"] = (
        "KeyError (unknown command) → tag 27 ['_rErr', 'KeyError', ...]. "
        "Registered errors → tag 32769."
    )
    vectors["marshalling"] = marshal

    # Write output
    out_dir = FSPath(__file__).resolve().parent.parent / "test" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "golden.json"

    with open(out_path, "w") as f:
        json.dump(vectors, f, indent=2)
        f.write("\n")

    print(f"Golden vectors written to {out_path}")
    print(f"  {len(vectors)} top-level sections")


class NoStreamError(StreamError):
    """Raised when a streaming operation is attempted on a non-stream link."""

    pass


if __name__ == "__main__":
    main()
