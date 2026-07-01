# Migration Plan: `moat.modbus` → extract `moat.lib.modbus`, drop `pymodbus`

## Goal

`moat.modbus` currently builds on `pymodbus`, which is large and has an
unstable API (the code is littered with `try/except ImportError` shims and a
`_compat.py` that monkeypatches pymodbus 3.9 to behave like 3.11). We extract
the **minimal protocol subset we actually use** into a new, dependency-free,
synchronous library `moat.lib.modbus` (stdlib only — no `pymodbus`, no
`anyio`), then refactor `moat.modbus` to use it and to stop working around
pymodbus quirks.

## Design principle: sans-IO

`moat.lib.modbus` is strictly **sans-IO**: it never opens a socket, touches a
serial port, sleeps, waits, or spawns a task. Every component is a pure
transform — bytes in → messages/PDUs out, messages in → bytes out. The only
mutable state permitted is the parser's own internal byte accumulator (this is
standard for sans-IO parsers and stays local to a framer instance). All real
I/O (TCP listeners, `anyio_serial`, reconnect timers, task groups) remains in
`moat.modbus`, which feeds bytes to the library and ships bytes the library
produces. This keeps the protocol core deterministic and unit-testable without
hardware or an event loop.

A consequence: the framers must know their **role** (client vs. server),
because the same function-code byte decodes to a *request* on a server and a
*response* on a client. The role is therefore a constructor flag on the framer
itself (see `framer.py`), not a separate decoder object threaded in by the
caller.

## Scope of pymodbus actually used (verified by grep)

- **PDU message classes** (`pymodbus.pdu.bit_message`, `…register_message`):
  function codes **1, 2, 3, 4, 5, 6, 15, 16** (read coils/discrete
  inputs/holding/input registers; write single/multiple coil/register).
  Referenced indirectly through `TypeCodec` singletons in `types.py`
  (`encoder`/`decoder`/`encoder_s`/`encoder_m`). Plus one `isinstance` check
  against `WriteSingleRegisterRequest` in `_main.py`.
- **Framers** (`pymodbus.framer`): `FramerSocket` (TCP/MBAP) and `FramerRTU`
  (RTU + CRC). API used: `buildFrame(msg)→bytes`, `handleFrame(data, dev_id,
  tid)→(used:int, pdu|None)`, `resetFrame()`. Each framer is paired with a
  `DecodePDU(server: bool)` that selects request-vs-response decoding — the
  role flag the new design folds onto the framer itself.
- **Errors**: `ExceptionResponse`, `ExcCodes.DEVICE_FAILURE` /
  `ExcCodes.GATEWAY_NO_RESPONSE`, `ModbusIOException`.
- **Server datastore/context** (`pymodbus.datastore`, `pymodbus.pdu.device`,
  `pymodbus.device`): `ModbusServerContext` (with `_devices`/`_slaves` internals
  the code pokes directly), `ModbusDeviceContext`/`ModbusSlaveContext` (base of
  `UnitContext`), `ModbusControlBlock`, `ModbusDeviceIdentification`,
  `ModbusSparseDataBlock` (base of `DataBlock`), `NoSuchSlaveException`/
  `NoSuchIdException`.
- **Indirection quirks**: `request.update_datastore(context)` and
  `request.execute(context)` — pymodbus methods the server leans on.
- **Util**: `hexlify_packets` (cosmetic logging only).

Nothing else from pymodbus is touched.

## Quirks / workarounds this migration eliminates

- `_compat.py` — monkeypatches pymodbus 3.9 framers (`handleFrame`) and
  fabricates an `ExcCodes` shim. **Deleted entirely.**
- Scattered `try/except ImportError` blocks choosing between pymodbus 3.9 and
  3.11 import paths (`server.py`, `dev/server.py`, `types.py`).
- The dual `unit_id` / `dev_id` naming: client PDUs use `unit_id`, server PDUs
  use `dev_id`, and `ValueList.readBlock` passes `dev_id=u.unit`. Normalized to
  **`unit_id`** everywhere.
- `DataBlock(ModbusSparseDataBlock)` inherits a base it almost fully overrides;
  only a no-op `validate()` survives. Becomes a plain class.
- `UnitContext(ModbusDeviceContext)` is entangled with pymodbus internals
  (`self.store`, `validate`, `getValues`, `setValues`, `process_request`,
  `update_datastore`). Becomes standalone.
- `request.update_datastore(context)` / `request.execute(context)` replaced by
  an explicit, owned dispatch.

## Dead code removed during the migration (verified unused)

- `moat/modbus/dev/server.py` (`Forwarder`, `Server`) — imported nowhere.
- `MockAioModbusServer` in `server.py` — empty subclass, unused.

## External consumers whose public API must be preserved

- `moat/dev/heat/kwb.py` — uses `dev_poll`.
- `moat/dev/sew/control.py` — uses `ModbusClient`, `HoldingRegisters`,
  `IntValue`, `SignedIntValue`.
- `tests/moat_modbus/`: `test_misc.py`, `test_link.py`, `test_dev_server.py`.

The high-level `moat.modbus` API (`ModbusClient`, `ModbusServer`,
`SerialModbusServer`, `RelayServer`, `UnitContext`, `create_server`,
`BaseValue` family, `TypeCodec` singletons, `DataBlock`, `dev_poll`,
`dev.device.*`, `dev.link.Register`) stays import-compatible. Only
implementation moves underneath.

---

## Target architecture

### `moat.lib.modbus` (new) — synchronous protocol core, stdlib-only

Plain Python (CPython 3.11+; no `pymodbus`, no `anyio`). Pure data-in/data-out;
no sockets, no clocks. Fully unit-testable without hardware.

- **`errors.py`** — `ExcCodes` (an `enum.IntEnum` covering at minimum
  `ILLEGAL_FUNCTION`, `ILLEGAL_DATA_ADDRESS`, `ILLEGAL_DATA_VALUE`,
  `SERVER_DEVICE_FAILURE`, `ACKNOWLEDGE`, `SERVER_DEVICE_BUSY`,
  `NEGATIVE_ACKNOWLEDGE`, `GATEWAY_PATH_UNAVAILABLE`, `GATEWAY_TARGET_NO_RESPONSE`;
  the aliases `DEVICE_FAILURE`→`SERVER_DEVICE_FAILURE` and
  `GATEWAY_NO_RESPONSE`→`GATEWAY_TARGET_NO_RESPONSE` are exposed for source
  compatibility) and `ModbusIOError(Exception)` (replaces `ModbusIOException`).
- **`_crc.py`** — `crc16(data: bytes) -> int`: CRC-16/Modbus, polynomial
  `0xA001` (reverse of `0x8005`), init `0xFFFF`, final XOR `0x0000`, processed
  LSB-first; emitted low byte then high byte. Table-free byte-wise loop.
- **`pdu.py`** — PDU base + request/response classes for FC 1, 2, 3, 4, 5, 6,
  15, 16, plus `ExceptionResponse`. Each has `function_code`, `encode()→bytes`
  (payload after the FC byte), `decode(data)` (populates from payload), and
  `isError()`. `transaction_id`/`unit_id` are mutable attributes stamped onto
  the parsed object by the framer (preserving current caller usage
  `reply.transaction_id`, `request.unit_id`). A role-aware helper
  `decode_pdu(byte_stream, *, server: bool) -> PDU` maps the leading FC byte →
  request class (when `server=True`) or response class (when `server=False`),
  raising `ModbusIOError` on an unknown FC. This is the only place the
  client/server distinction enters the PDU layer; the framer picks the flag
  and calls it.
  Each `Request` carries an `execute(context)` method that, given a minimal
  **Context** (a `typing.Protocol` exposing per-kind `get_values(addr, count)`
  and `set_values(addr, values)`), returns the matching `Response` or an
  `ExceptionResponse` — this is the clean, owned replacement for pymodbus'
  `update_datastore`/`execute` indirection and lives in the protocol layer so
  the server stays thin.
- **`framer.py`** — `FramerTCP(role, ...) → bytes` (MBAP: 7-byte header
  `[tid_hi, tid_lo, 0, 0, len_hi, len_lo, unit_id]` + PDU) and
  `FramerRTU(role, ...)` (address byte + PDU + 2-byte CRC via `_crc.crc16`).
  `role` is a required boolean constructor flag: `"server"` (alias `True`)
  means the framer decodes incoming bytes as **requests**; `"client"` (alias
  `False`) means it decodes them as **responses**. Outgoing direction is
  implied by what the peer expects, so `buildFrame` is role-agnostic. Both
  share the contract `buildFrame(msg)→bytes` and
  `handleFrame(data, ...)→(used:int, pdu|None)` where `used==0` signals “frame
  incomplete, wait for more bytes”, plus `resetFrame()`. Internally each
  framer holds a private byte accumulator (the only mutable state permitted
  under the sans-IO rule) and delegates PDU decoding to `decode_pdu(...,
  server=self.role_is_server)`. `FramerRTU.handleFrame` validates the CRC and
  rejects malformed frames by consuming the bad segment.
- **`__init__.py`** — re-exports the public surface.

### `moat.modbus` (refactored) — async client/server/values, now on `moat.lib.modbus`

Keeps its current public API and file layout; internals rewired.

- `types.py` — `TypeCodec` singletons point at `moat.lib.modbus.pdu` classes.
  `DataBlock` becomes a plain class (drops `ModbusSparseDataBlock` base and the
  `validate()` stub). `BaseValue` family is pure `struct` and unchanged.
- `client.py` — imports framers/PDU/exceptions from `moat.lib.modbus`;
  consistently uses `unit_id`; drops `_compat`. Reader loops keep their shape
  (same `(used, pdu)` contract).
- `server.py` — `BaseModbusServer` owns its own `units` dict and a small
  `Identity` dataclass (no `ModbusControlBlock`/`ModbusDeviceIdentification`/
  `ModbusServerContext`). `UnitContext` is standalone, holding four
  `DataBlock`s keyed by `c/d/i/h`, and exposes the `Context` protocol that
  `moat.lib.modbus.pdu.Request.execute` consumes. Request dispatch goes through
  `moat.lib.modbus`; `NoSuchSlaveException` becomes a local `KeyError` check.
  `create_server` unchanged. `RelayServer`/`SerialModbusServer` adapted to the
  new framer/PDU objects.
- `_compat.py` deleted; `__init__.py` stops importing it.
- `_main.py` / `__main__.py` — `WriteSingleRegisterRequest` isinstance check
  switched to the `moat.lib.modbus` equivalent; CLI behaviour unchanged.
- `dev/server.py` deleted; `dev/server_unit.py` updated to the new
  `UnitContext`; `dev/{device,link,poll}.py` reviewed (expected: no public-API
  change, only internal attribute access adjustments if any).

---

## Tasks

Ordered by dependency. Each task is independently verifiable. Foundational
protocol pieces (Tasks 1–5) land first; the `moat.modbus` refactor (Tasks 6–10)
depends on them; packaging/docs/cleanup close out.

### Task 1: Scaffold `moat.lib.modbus` package, packaging, and docs

**Files:**
- Create: `moat/lib/modbus/__init__.py` (empty re-export hub, filled by later tasks)
- Create: `packaging/moat-lib-modbus/pyproject.toml`
- Create: `packaging/moat-lib-modbus/README.md` (synopsis + `% start main`/`% end main` markers, per repo doc convention)
- Create: `docs/moat-lib-modbus/index.md`, `docs/moat-lib-modbus/api.rst`, `docs/moat-lib-modbus/ARCHITECTURE.md`
- Create: `tests/moat_lib_modbus/__init__.py` (empty)

**Purpose:** Establish the new package skeleton following the
`moat/X/Y/**.py` + `docs/moat-X-Y` + `packaging/moat-X-Y` + `tests/moat_X_Y`
convention. `pyproject.toml` declares deps `anyio` (none for the lib itself —
stdlib only) and `moat-util` only if needed; `requires-python = ">=3.11"`.

**Expected Result:**
- Package importable: `python -c "import moat.lib.modbus"` succeeds (empty namespace).
- `ty check` clean (nothing to check yet).
- Docs build placeholder renders.

### Task 2: `errors.py` — `ExcCodes` and `ModbusIOError`

**Files:**
- Create: `moat/lib/modbus/errors.py`
- Modify: `moat/lib/modbus/__init__.py` (re-export `ExcCodes`, `ModbusIOError`)
- Test: `tests/moat_lib_modbus/test_errors.py`

**Purpose:** Define `ExcCodes` as `enum.IntEnum` with the Modbus standard
exception codes and the two source-compatibility aliases
(`DEVICE_FAILURE`, `GATEWAY_NO_RESPONSE`) used by the current `moat.modbus`
code, plus `ModbusIOError(Exception)`.

**Expected Result:**
- `ExcCodes.DEVICE_FAILURE == ExcCodes.SERVER_DEVICE_FAILURE == 4`;
  `ExcCodes.GATEWAY_NO_RESPONSE == ExcCodes.GATEWAY_TARGET_NO_RESPONSE == 11`.
- Test asserts the integer values and alias equality.
- `ty check` clean on `errors.py` (added to `tool.ty.src.include` implicitly via
  the `moat/lib/` glob — confirm by running `ty check --output-format github`).

### Task 3: `_crc.py` — CRC-16/Modbus

**Files:**
- Create: `moat/lib/modbus/_crc.py`
- Modify: `moat/lib/modbus/__init__.py` (export `crc16`)
- Test: `tests/moat_lib_modbus/test_crc.py`

**Purpose:** Implement `crc16(data: bytes) -> int` per the Modbus spec:
polynomial `0xA001` (bit-reversed `0x8005`), init `0xFFFF`, no final XOR,
LSB-first processing, byte-wise loop (no lookup table). Known-answer tests pin
the implementation.

**Expected Result:**
- `crc16(b"")` == `0xFFFF`.
- Known vectors pass, e.g. `crc16(bytes([0x01,0x03,0x00,0x00,0x00,0x0A]))` equals
  the documented value (asserted against a vector table built from the spec;
  at least three vectors covering read-request, write-response, and a
  multi-register frame).
- Round-trip: appending `crc16(payload).to_bytes(2,"little")` and re-scanning
  validates.
- `ty check` clean.

### Task 4: `pdu.py` — PDUs, `ExceptionResponse`, `decode_pdu`, and `Request.execute`

**Files:**
- Create: `moat/lib/modbus/pdu.py`
- Modify: `moat/lib/modbus/__init__.py` (re-export PDU classes, `decode_pdu`, `ExceptionResponse`)
- Test: `tests/moat_lib_modbus/test_pdu.py`

**Purpose:** Define a `PDU` base and request/response classes for FC 1, 2, 3,
4, 5, 6, 15, 16 plus `ExceptionResponse`. Each class: class attribute
`function_code`; `encode() -> bytes` (payload after the FC byte);
`decode(data: bytes) -> None`; `isError() -> bool` (True only for
`ExceptionResponse`). `transaction_id`/`unit_id` are plain mutable attributes
the framer stamps on. Provide the role-aware free function
`decode_pdu(data: bytes, *, server: bool) -> PDU` that reads the leading FC
byte and instantiates the **request** class (when `server=True`) or
**response** class (when `server=False`); an unknown FC raises
`ModbusIOError`. This is the single decision point where the client/server
distinction enters the PDU layer; the framer holds the flag and calls this.
Each `Request` defines `execute(context) -> Response` operating against a
`Context` `typing.Protocol` with per-kind `get_values(address, count)
-> list[int]` and `set_values(address, values) -> None`; illegal-address/value
conditions yield an `ExceptionResponse` with the right `ExcCodes`.

**Expected Result:**
- For every FC: `req.encode()` round-trips through `decode_pdu(req_bytes,
  server=True)` + the matching class’s `decode`, reproducing `address`,
  `count`, `registers`/`bits`/`value`; responses likewise with `server=False`.
- `ExceptionResponse(fc, code).encode()` == `bytes([fc|0x80, code])`.
- `Request.execute` against an in-memory fake `Context` returns the expected
  `Response` for a read, and the expected write mutation for a write; an
  out-of-range address yields `ExceptionResponse(_, ExcCodes.ILLEGAL_DATA_ADDRESS)`.
- `ty check` clean.

**Alternative:** Keep dispatch in `moat.modbus.server` as a free function
instead of methods on `Request`. Trade-off: keeps `moat.lib.modbus` purely
about bytes↔objects with no “context” concept, but duplicates FC→datastore logic
that is genuinely protocol-level and would benefit from independent unit
testing. Recommended: methods on `Request` (cleaner, testable, kills the
pymodbus `update_datastore` quirk at the right layer).

### Task 5: `framer.py` — `FramerTCP` (MBAP) and `FramerRTU`, role-flagged

**Files:**
- Create: `moat/lib/modbus/framer.py`
- Modify: `moat/lib/modbus/__init__.py` (re-export `FramerTCP`, `FramerRTU`)
- Test: `tests/moat_lib_modbus/test_framer.py`

**Purpose:** Two framers, each constructed as `FramerTCP(role)` /
`FramerRTU(role)` where `role` is the required client/server flag (`True` /
`"server"` ⇒ decode incoming bytes as **requests**; `False` / `"client"` ⇒
decode as **responses**). The flag is stored on the instance and passed down to
`decode_pdu(..., server=self.role_is_server)`, so the caller no longer
constructs and threads a separate `DecodePDU` object. Contract:
`buildFrame(msg)->bytes` (role-agnostic — outgoing bytes are what the peer
expects) and `handleFrame(data, ...)->(used:int, pdu|None)` with `used==0`
meaning “incomplete, feed more bytes”. Each framer owns a private byte
accumulator (the sole mutable state allowed under the sans-IO rule).
`FramerTCP` parses the 7-byte MBAP header (validates protocol id 0 and length),
stamps `transaction_id` and `unit_id` on the decoded PDU. `FramerRTU` scans for
a complete `address+PDU+CRC` frame, validates the CRC via `_crc.crc16`,
discards bad bytes, and stamps `unit_id` (TID forced to 0, matching current
`SerialHost`). `resetFrame()` clears the accumulator.

**Expected Result:**
- `FramerTCP(True)` and `FramerTCP(False)` both round-trip: `buildFrame(msg)`
  fed back to `handleFrame` of a same-role framer yields the original PDU, for a
  sample request and response across all four register kinds.
- Role matters: a request built by a server-role framer decodes as a request
  only under a server-role framer, and as a response-shaped object (or error)
  under a client-role framer — assert the asymmetry explicitly.
- Partial frames: feeding the first half of a TCP frame returns `(0, None)`,
  then completing it yields the PDU.
- RTU: a frame with a corrupted payload byte is rejected (CRC mismatch) and
  scanning resumes at the next plausible boundary; a valid frame decodes.
- `ty check` clean.

**Dependency:** Tasks 2, 3, 4.

### Task 6: Rewire `moat.modbus.types` to `moat.lib.modbus`; slim `DataBlock`

**Files:**
- Modify: `moat/modbus/types.py`
- Test: `tests/moat_modbus/test_misc.py` (still passes unchanged)

**Purpose:** Point the four `TypeCodec` singletons’ `encoder`/`decoder`/
`encoder_s`/`encoder_m` at the `moat.lib.modbus.pdu` classes. Drop the
`ModbusSparseDataBlock` base from `DataBlock` (remove the import-shim `try`/
`except` block and the no-op `validate()`), making it a plain class. `BaseValue`
family unchanged.

**Expected Result:**
- `from moat.modbus.types import HoldingRegisters, IntValue` still works.
- `DataBlock` no longer imports anything from `pymodbus`.
- `test_misc.py` green.
- `ty check` clean on `types.py`.

**Dependency:** Tasks 2, 4.

### Task 7: Refactor `moat.modbus.client` onto `moat.lib.modbus`

**Files:**
- Modify: `moat/modbus/client.py`
- Test: `tests/moat_modbus/test_misc.py`, `tests/moat_modbus/test_link.py`

**Purpose:** Replace `pymodbus` imports (`FramerRTU`, `FramerSocket`,
`DecodePDU`, `ExceptionResponse`, `ExcCodes`, `ModbusIOException`) with
`moat.lib.modbus` equivalents. Framers are now constructed with their role
flag: `Host`/`SerialHost` build a **client-role** framer
(`FramerTCP(False)` / `FramerRTU(False)`) since they decode responses — no
separate `DecodePDU` object is threaded in. Use `unit_id` uniformly in
`ValueList.readBlock` and `Unit.process_request` (drop the `dev_id=`
argument). Reader loops keep their existing `(used, pdu)` structure.
`ModbusError` unchanged.

**Expected Result:**
- `test_misc.py` client side green; `test_link.py` green.
- No `pymodbus` imports remain in `client.py`.
- `ty check` clean.

**Dependency:** Tasks 5, 6.

### Task 8: Refactor `moat.modbus.server` — drop pymodbus context/control/identity

**Files:**
- Modify: `moat/modbus/server.py`
- Test: `tests/moat_modbus/test_misc.py`, `tests/moat_modbus/test_dev_server.py`

**Purpose:** `BaseModbusServer` owns its own `units: dict` and a small local
`Identity` dataclass (vendor/product fields) — no `ModbusServerContext`,
`ModbusControlBlock`, `ModbusDeviceIdentification`. `UnitContext` becomes
standalone: four `DataBlock`s keyed `c/d/i/h`, exposes the `Context` protocol
(`get_values`/`set_values`), and dispatches incoming PDUs through
`moat.lib.modbus.pdu.Request.execute(self)` (falling back to a custom
`process_request` hook where present, preserving `dev/server_unit.ServerUnitContext`).
`NoSuchSlaveException` → local `KeyError` branch. `ModbusServer` /
`SerialModbusServer` / `RelayServer` construct **server-role** framers
(`FramerTCP(True)` / `FramerRTU(True)`) since they decode requests, and use
the new PDUs. `create_server` unchanged. Delete `MockAioModbusServer`.

**Expected Result:**
- `test_misc.py` server side green; `test_dev_server.py` green.
- No `pymodbus` imports remain in `server.py`.
- `ty check` clean.

**Dependency:** Tasks 5, 6.

**Alternative:** Keep a thin `ModbusServerContext`-shaped wrapper to minimize
diff. Trade-off: preserves the quirk we set out to remove. Recommended:
standalone `UnitContext`.

### Task 9: Cleanup `moat.modbus` glue — `_compat`, `__init__`, dead code, CLI imports

**Files:**
- Delete: `moat/modbus/_compat.py`
- Delete: `moat/modbus/dev/server.py`
- Modify: `moat/modbus/__init__.py` (drop `_compat` import)
- Modify: `moat/modbus/_main.py` (`WriteSingleRegisterRequest` isinstance → `moat.lib.modbus` class)
- Modify: `moat/modbus/__main__.py` (review imports; no behavioural change)
- Test: `tests/moat_modbus/test_misc.py`

**Purpose:** Remove the compatibility shim and confirmed-dead modules; switch
the last stray `pymodbus` symbol used in the CLI to its `moat.lib.modbus`
equivalent.

**Expected Result:**
- `git grep -n pymodbus moat/modbus` returns **zero** hits.
- `python -m moat.modbus` CLI still imports.
- `test_misc.py` green; `ty check` clean.

**Dependency:** Tasks 6, 7, 8.

### Task 10: Update `moat.modbus.dev.*` to the new internals

**Files:**
- Modify: `moat/modbus/dev/server_unit.py`
- Review/modify as needed: `moat/modbus/dev/device.py`, `moat/modbus/dev/link.py`, `moat/modbus/dev/poll.py`
- Test: `tests/moat_modbus/test_dev_server.py`, `tests/moat_modbus/test_link.py`

**Purpose:** `ServerUnitContext` adapts to the standalone `UnitContext`
(attributes like `self.store[...]` move to whatever the new `UnitContext`
exposes). `device.py`/`link.py`/`poll.py` consume only the high-level
`moat.modbus` API; adjust any internal-attribute access and confirm `dev_poll`
still wires client registers into server `UnitContext`s.

**Expected Result:**
- `test_dev_server.py` (transformation serving, remapping, forward, const,
  age-based rereading) all green.
- `test_link.py` green.
- `ty check` clean.

**Dependency:** Task 8.

### Task 11: Verify external consumers compile and behave

**Files:**
- Review (no change expected): `moat/dev/heat/kwb.py`, `moat/dev/sew/control.py`
- Test: import-smoke + any existing `moat.dev.*` tests touching modbus

**Purpose:** Confirm the public `moat.modbus` surface (`ModbusClient`,
`HoldingRegisters`, `IntValue`, `SignedIntValue`, `dev_poll`) still satisfies
these consumers with no source changes.

**Expected Result:**
- `python -c "import moat.dev.heat.kwb, moat.dev.sew.control"` succeeds.
- If any consumer breaks, fix the consumer minimally and note it.

**Dependency:** Tasks 7, 8, 10.

### Task 12: Packaging — drop `pymodbus`, add `moat-lib-modbus`

**Files:**
- Modify: `packaging/moat-modbus/pyproject.toml` (deps: remove `pymodbus ~= 3.9.0`, add `moat-lib-modbus ~= 0.1`)
- Modify: `packaging/moat-modbus/debian/control` (drop `python3-pymodbus (>= 3.7)`, add `moat-lib-modbus`)
- Modify: root `pyproject.toml` line 44 (remove `"pymodbus ~= 3.9.0"` from the dev/test dependency list)
- Confirm: `packaging/moat-lib-modbus/pyproject.toml` (from Task 1) lists no runtime deps beyond stdlib

**Purpose:** Cut the pymodbus dependency everywhere it is declared and declare
the new internal library.

**Expected Result:**
- `git grep -n pymodbus packaging pyproject.toml` shows only historical
  references (if any) outside active dependency declarations.
- `pip install -e packaging/moat-lib-modbus && pip install -e packaging/moat-modbus` resolves without pymodbus.

**Dependency:** Tasks 1–10.

### Task 13: Documentation

**Files:**
- Modify: `docs/moat-modbus/ARCHITECTURE.md` (replace “Builds on `pymodbus`
  primitives…” with “Builds on `moat.lib.modbus`…”; drop the `_compat.py`
  bullet)
- Modify: `docs/ARCHITECTURE.md` (add `moat-lib-modbus` to the foundation index
  with a one-paragraph entry + link to `docs/moat-lib-modbus/ARCHITECTURE.md`)
- Finalize: `docs/moat-lib-modbus/ARCHITECTURE.md`, `index.md`, `api.rst`
- Modify: `packaging/moat-modbus/README.md` (drop “frontend for pymodbus”
  wording; describe the split)

**Purpose:** Reflect the new two-layer architecture and the removal of pymodbus.

**Expected Result:**
- Docs build cleanly; no dangling references to `pymodbus` or `_compat`.
- `moat-lib-modbus` appears in the top-level subsystem index.

**Dependency:** Tasks 1–10.

### Task 14: Final test / lint / typecheck sweep

**Files:** none (validation only)

**Purpose:** Whole-tree verification: `pytest tests/moat_modbus tests/moat_lib_modbus`
(write output to a temp file per repo guidelines), `ty check --output-format
github`, `ruff check`/`ruff format` only as needed to fix reported errors (do
not run formatters proactively). Confirm `git grep -n pymodbus moat/ packaging/
pyproject.toml` is empty.

**Expected Result:**
- All modbus tests green; no regressions in `moat.dev.*` modbus-touching tests.
- `ty check` clean on newly added/modified files.
- Zero `pymodbus` references in shipped code/packaging.

**Dependency:** all prior tasks.

---

## Risks & dependencies

- **Behaviour parity for edge cases**: pymodbus silently tolerates some
  malformed frames; the new RTU framer’s reject-and-rescan strategy must be
  validated against real captured traffic (the `monitor`/relay CLI in
  `_main.py` is the tool for this). Mitigation: known-vector tests + a manual
  serial smoke test before closing the issue.
- **`Request.execute` context contract**: the `Context` `Protocol` must cover
  everything `dev/server_unit.py` needs (age-based refresh, on-demand forward).
  Risk that `update_datastore` did something subtle we depend on. Mitigation:
  `test_dev_server.py` exercises these paths; keep it green throughout Task 8/10.
- **`unit_id` rename blast radius**: every place that read `dev_id` from a
  pymodbus PDU must move to `unit_id`. Mitigation: `ty check` + the dev-server
  tests catch mismatches.
- **No sub-issues yet**: per request, a single epic issue is filed; sub-issues
  are deferred until this plan is refined/approved.

## Suggested split (if the team prefers smaller PRs)

The plan is one cohesive change, but it splits naturally along the dependency
seam:

- **PR A — `moat.lib.modbus` (Tasks 1–5):** lands the new library with its own
  tests, nothing in `moat.modbus` changes yet. Independently green.
- **PR B — `moat.modbus` refactor + cleanup + packaging + docs (Tasks 6–14):**
  switches `moat.modbus` to the new library and removes pymodbus. Depends on PR A.

Either way, the epic tracks the whole migration.
