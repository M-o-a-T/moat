# Plan: `moat-lib-rpc` — TypeScript port of `moat.lib.rpc`

Status: **Planning** (no code yet). Tracks Beads issue `moat-<TBD>` (created alongside this plan).
Target location: `ts/msg/moat-lib-rpc/` (package name `moat-lib-rpc` on npm).

## 1. Goal

Create a modern, publishable TypeScript/JavaScript NPM package that is a faithful
port of MoaT's Python `moat.lib.rpc` library. It must speak the **same wire
protocol** so that a TS client/server interoperates byte-for-byte with a Python
client/server. The library core follows **sans-IO** principles; a thin async
adapter provides a nice client/server UX.

Mirrored capabilities (phase 1 = wire-compatible core):

- Request/response RPC with asynchronous replies.
- Bidirectional streaming over a single sub-channel, with flow control.
- Cancellation (client- and server-initiated) and exception forwarding.
- Hierarchical, path-addressed command dispatch (`cmd_*` / `stream_*` / `sub_*`).
- Built-in meta commands: `dir_`, `doc_`, `rdy_` (matching Python semantics).
- CBOR codec (`cbor2`) with MoaT's standard extension tags (Path, proxies,
  errors, sets, datetimes).
- Transports: WebSocket (one CBOR message per frame) and raw TCP (back-to-back
  CBOR, incremental decode), plus a stdin/stdouut pipe driver for tests.

Phase 2+ (stretch, tracked as follow-ups): auth (DH handshake), `rpc_on_rpc`
nesting, the alert subsystem, the `Reliable*` wrapper, and the full `app/*`
command-tree framework. These sit *on top of* the core and do not affect wire
compatibility.

## 2. Non-goals (for this plan)

- Porting the MicroPython/embedded variants.
- Porting `moat.link`, `moat.micro`, or any `app/*` device drivers (i2c, spi,
  fs, net, …). Those are consumers of this library, not part of it.
- Browser bundling as a primary target (Node is primary; a browser ESM build is
  a bonus if `cbor2` and the transport permit).

## 3. Directory layout

```
ts/msg/
  PLAN.md                      # this file
  moat-lib-rpc/
    package.json               # npm metadata, exports map, scripts
    tsconfig.json              # strict TS, ESM, declarations
    tsconfig.build.json        # build-only (excludes tests)
    README.md                  # synopsis + main (Myst-friendly)
    LICENSE                   # GPL-3.0-or-later (matches repo)
    Makefile                   # build / minify / test / publish targets
    .eslintrc / .prettierrc    # lint/format config
    .gitignore                 # node_modules, dist, *.tsbuildinfo, coverage
    src/
      index.ts                 # public barrel + re-exports
      const.ts                 # B_*, E_*, S_*, SD_* constants
      errors.ts                # StreamError taxonomy + decodeStreamError()
      wire.ts                  # i_f2wire / wire2i_f header packing
      codec.ts                 # cbor2 wiring + MoaT tag table
      path.ts                  # Path type (encode/decode tag 39)
      proxy.ts                 # Proxy/DProxy + error marshalling (tags 27/32769)
      core/
        handler.ts             # RpcCore — sans-IO multiplexer (≈ HandlerStream)
        link.ts                # StreamLink (≈ MsgLink / StreamLink)
        msg.ts                 # Msg envelope + MsgResult (≈ Msg/MsgResult)
      dispatch/
        handler.ts            # MsgHandler base (cmd_/stream_/sub_, dir_/doc_/rdy_)
        sender.ts             # MsgSender + Caller (awaitable + async iterator)
        tree.ts               # minimal RootCmd/DirCmd (stretch)
      transport/
        ws.ts                  # WebSocket client/server (one CBOR per frame)
        tcp.ts                 # raw TCP client/server (incremental CBOR)
        pipe.ts                # stdin/stdout driver (for interop tests)
        framing.ts            # incremental cbor2 decoder helper, msg_prefix
      async/
        adapter.ts             # sans-IO core <-> Promises/AsyncIterators
        caller.ts              # Caller: thenable + AsyncIterable + ctx-manager
    examples/
      client.ts                # async client demo
      server.ts                # async server demo
      README.md
    test/
      unit/*.test.ts           # wire, codec, errors, dispatch, core state machine
      property/*.test.ts        # fast-check property tests for header/codec round-trips
      golden/*.test.ts          # known-byte vectors (TS↔Python agreed)
      loopback/*.test.ts        # TS↔TS end-to-end over in-memory + WS + TCP
      interop/*.test.ts         # TS↔Python (spawns Python via subprocess)
      fixtures/                 # python scripts + golden .cbor files
    scripts/
      build.mjs                 # tsup/esbuild pipeline producing ESM/CJS/min
      golden-gen.py             # regenerates golden vectors from Python
    dist/                       # build output (gitignored), staged for npm pack
```

## 4. MoaT-RPC wire protocol (authoritative reference)

Source of truth: the Python code in `moat/lib/rpc/{const,errors,msg,base}.py`
and `moat/lib/rpc/stream/base.py`. The prose in
`packaging/moat-lib-rpc/README.md` ("Transport Specification") is helpful but
**slightly out of date**; where they disagree, the **code wins**. The TS port
must reproduce the code's behaviour exactly.

### 4.1 Framing / transport

- Each RPC message is one **CBOR array**.
- Over **WebSocket** (`moat.lib.stream._cbor._CBORMsgBlk`): one CBOR array per
  WS frame. `send = ws.send(codec.encode(msg))`; `recv = codec.decode(ws.recv())`.
- Over **raw TCP / USB** (`_CBORMsgBuf`): CBOR arrays streamed back-to-back with
  **no length prefix**; CBOR is self-delimiting. Decode incrementally, feeding
  bytes to a streaming decoder and extracting one array at a time. An optional
  single `msg_prefix` byte may precede each message to multiplex console data;
  if used, the prefix byte must be ≥ 0xF8 and the framed message must be sent
  atomically (prefix + payload in one write).
- Messages are **reliable, ordered**. If the underlying medium can lose/reorder,
  a `Reliable*` wrapper (phase 2) is required — out of scope for the core.

### 4.2 Header integer packing

Defined in `moat/lib/rpc/stream/base.py`:

```
i_f2wire(id, flag):           # encode
    assert id != 0
    assert 0 <= flag <= 3 or flag == B_WARNING_INTERNAL  # 7
    if id > 0: id -= 1
    return (id << 2) | (flag & 3)

wire2i_f(w):                  # decode (before sign flip)
    f = w & 3
    id = w >> 2
    if id >= 0: id += 1
    return (id, f)
```

On the receiving side (`HandlerStream.msg_in`), the decoded id is then
**sign-flipped with plain negation**: `i = -i`. Positive ids are allocated by
the originator (≥ 1); the responder sees them as negative and reuses the
negative id in replies. ID `0` is never sent as a live id.

Example round-trip (verified against the code): originator id=1, flag=0 →
wire `0`; responder decodes `(1,0)` → flips to `-1`; reply with id=-1, flag=0
→ wire `-4`; originator decodes `(-1,0)` → flips to `1`. ✅

**JS implementation caveat:** JS `<<` / `>>` are 32-bit signed and would
truncate ids ≥ 2³⁰. The TS port must use plain arithmetic, not bitwise shifts:

```
encode(id, flag):  return (id > 0 ? id - 1 : id) * 4 + (flag & 3)
decode(w):         flag = w & 3; id = Math.floor(w / 4); if (id >= 0) id++; i = -id
```

(`Math.floor` matches Python's floor `>>` for negatives; `& 3` is safe for the
2-bit flag.) IDs stay small in practice (sequential allocation + recycle), but
arithmetic keeps it correct up to Number's 2⁵³ limit.

**ID allocation:** originator maintains a free-id pool; allocate by popping a
freed id or incrementing a counter. An id may be reused only after **both**
directions have sent their final (stream-bit-clear) message. Python delays
reuse ~1 s; the TS core may recycle immediately on dual-final, since wire
compat only requires uniqueness-while-live.

### 4.3 Flags (low 2 bits of the header)

| constant              | value | meaning                                              |
|-----------------------|------:|------------------------------------------------------|
| (none)                | 0     | final message for this direction (out-of-band)       |
| `B_STREAM`            | 1     | starts/continues a data stream                        |
| `B_ERROR`             | 2     | terminal error (stream bit clear)                    |
| `B_WARNING`           | 3     | warning / OOB info (=`B_STREAM \| B_ERROR`)           |
| `B_WARNING_INTERNAL`  | 7     | flow-control warning (reconstructed, see below)      |

Only the low 2 bits travel on the wire. `B_WARNING_INTERNAL` (7) is **not**
transmitted distinctly; it is reconstructed on decode: a message with flag `3`
whose payload is a single integer is reclassified as internal flow control
(`flag = 7`). Consequently **user warnings may not consist of a lone integer**
(the codec appends an empty `{}` to disambiguate — see §4.6).

### 4.4 Stream states & directions

From `const.py`: `S_NEW=4`, `S_ON=5`, `S_OFF=6`, `S_END=3` (per direction,
tracked separately for in/out); `SD_NONE=0`, `SD_IN=1`, `SD_OUT=2`, `SD_BOTH=3`.
The TS `Msg` port tracks `_streamIn` / `_streamOut` with the same transitions
documented in `msg.py` (`ml_recv`/`ml_send`/`prep_stream`/`no_stream`). An
interaction is complete when **both** directions reach `S_END` (each side sent
exactly one stream-bit-clear message).

### 4.5 Error codes & taxonomy

From `const.py` and `errors.py` (`StreamError.__new__` maps a single-int
payload to a concrete type):

| code        | value | mapped exception        |
|-------------|------:|-------------------------|
| `E_UNSPEC`  | -1   | `StopMe`                |
| `E_NO_STREAM`| -2  | `NoStream`              |
| `E_CANCEL`  | -3   | `CancelledError`        |
| `E_NO_CMDS` | -4   | `NoCmds`                |
| `E_SKIP`    | -5   | `SkippedData`           |
| `E_MUST_STREAM`| -6 | `MustStream`           |
| `E_ERROR`   | -7   | `RemoteError`           |
| `E_NO_CMD`  | -11  | `NoCmd(E_NO_CMD - m)`   |
| (≥ 0)       |  n   | `Flow(n)` (flow control; not a thrown Error) |

Non-int payloads (proxies/strings/exceptions) reconstruct the original
exception or fall back to `RemoteError`. The TS port defines an `RpcError`
hierarchy mirroring these (`StopMe`, `NoStream`, `NoCmds`, `NoCmd`,
`SkippedData`, `MustStream`, `RemoteError`, `NotReadyError`,
`Short/LongCommandError`) plus a `Flow` signal object (not thrown; surfaced via
the flow-control callback).

### 4.6 Payload conventions

- A message array is `[header, *args, ?kwargsMap]`.
- **First** message of a call (incoming side): `[header, cmdPath, *args, ?kw]`.
  `cmdPath` is a `Path` (CBOR tag 39); if the args tail is empty the path
  defaults to the empty `Path` (`msg_in`: `cmd = a.pop(0) if a else Path()`).
- Subsequent messages: `[header, *args, ?kw]`.
- **kwargs** use `moat.util.pp.push_kw` / `pop_kw`:
  - Encode (`push_kw`): append the kwargs `Map` to the args array iff (a) kwargs
    is non-empty, **or** (b) the last positional arg is itself a `Map`, **or**
    (c) it is a user warning consisting of a single integer (append `{}`). The
    trailing map is otherwise omitted.
  - Decode (`pop_kw`): if the last array element is a `Map`, pop and treat as
    kwargs; else `{}`.
  - The TS port uses `Map` for all CBOR maps (cbor2 default) so kwargs vs.
    positional-map disambiguation is positional and unambiguous.
- **Sentinels:** `NotGiven` ≡ `Ellipsis` → CBOR `undefined` (0xF7). `true`/`
  false`/`null` map naturally. Booleans must be emitted as CBOR bool (not
  int 0/1).
- **Bytes vs text:** CBOR byte strings → `Uint8Array`; CBOR text → `string`.
  The codec must preserve the distinction (paths may contain `Uint8Array`
  elements).

### 4.7 Lifecycle / exchange rules

- Originator allocates a fresh positive id, sends the command (flag 0 or 1).
- Responder decodes, flips sign, dispatches by path, and replies using the
  (negative) id. Exactly one stream-bit-clear message must be sent in each
  direction; the interaction ends when both are delivered.
- Streaming: the originator may not send streamed data before receiving the
  initial reply with the stream bit set. Initial and final messages are
  out-of-band. Warnings (flag 3) attach conceptually to the following message.
- Late/extra messages after `S_END` are logged and dropped (matches `ml_recv`).

### 4.8 Flow control

A recipient with bounded buffer may send a warning (flag 3) whose single
non-negative integer advertises how many streamed items the sender may emit
without acknowledgement. The sender credits-down per item; the recipient sends
more credit as buffer frees. `E_SKIP` (-5) signals a dropped item due to
resource exhaustion. The TS core implements credit counters as pure state and
emits/absorbs these via the sans-IO boundary.

## 5. Codec strategy (`cbor2`)

### 5.1 Choice

Use the npm package **`cbor2`** (v2.3.0, MIT, hildjj/cbor2) — RFC 8949,
ESM/CJS, custom `Tag` handling, and a streaming `Decoder`/`DecodeStream` for
incremental TCP decode. (The existing `moat/nodered/moat-meta-codec` uses the
older `cbor` ^9; this package standardises on `cbor2`.)

### 5.2 MoaT extension tag table

Mirror `moat/lib/codec/_moat_cbor.py` + `moat/lib/proxy`:

| tag    | encodes                         | wire shape                          |
|--------|---------------------------------|-------------------------------------|
| 39     | `Path`                          | array of path elements              |
| 27     | `DProxy` / wrapped object / error | `[name, *args, ?kw]`              |
| 32769  | `Proxy` (by name)               | string/int name                     |
| 258    | `Set`                           | array                               |
| 1      | `Date` (epoch seconds)          | float                               |
| 0      | `Date` (ISO string) — decode only | string                           |
| 2 / 3  | bignum / neg-bignum             | byte string                         |
| 55799  | self-describe CBOR (passthrough) | —                                  |

Register these as a `cbor2` tag map on both encoder and decoder. Unknown tags
decode to a `Tag` object (matches Python's fallback) so forward-compat holds.

### 5.3 `Path` type (`src/path.ts`)

- Immutable, backed by an array of elements (`string | number | bigint |
  boolean | null | Uint8Array | Path`).
- Encode: `new Tag(39, elements)` → cbso. Decode: tag 39 → `Path.build(elems)`.
- Support `build()`, `raw`, `parent`, concatenation, and the slash/dot string
  forms needed for logging and tests. (Full parser fidelity is stretch; the wire
  only needs the array form.)

### 5.4 Proxy / error marshalling (`src/proxy.ts`)

- Maintain a name⇆constructor registry mirroring `moat.lib.proxy`.
- Encode an `Error`: prefer a registered proxy name under tag 32769; else emit
  tag 27 `["_rErr", errorClassName, ...args]` (matches `enc_any`'s exception
  fallback). Decode reverses both, reconstructing an `RpcError` subtype when
  the class is unknown.
- `DProxy` (tag 27) round-trips `[name, *args, ?kw]` for opaque objects.

### 5.5 Incremental decode for TCP

Use `cbor2`'s streaming decoder fed by socket `'data'` events; emit one decoded
array per complete CBOR object. Handle the optional `msg_prefix` byte by
peeking/scan-ahead (mirrors `_CBORMsgBuf.recv`).

## 6. Sans-IO core architecture

The Python `HandlerStream` is labelled sans-IO but internally uses taskgroups
and queues. The **TS core will be stricter**: a pure, synchronous state machine
with **no promises, timers, or I/O**. Async behaviour lives entirely in the
`transport/` + `async/` layers.

### 6.1 `RpcCore` (`src/core/handler.ts`) — ≈ `HandlerStream`

- Holds the live sub-channel map (`id → StreamLink`), the id allocator, and
  per-direction credit counters.
- **Inputs (sync):** `core.feed(message: unknown[]): void` — decode header,
  flip sign, route to an existing `StreamLink` or spawn a new one and invoke
  the registered command handler.
- **Outputs (sync):** `core.drain(): unknown[][]` returns queued outbound
  frames; alternatively a callback `core.onOutgoing = (frame) => …`. The async
  adapter pumps these to the transport.
- **Callbacks** the core invokes on the adapter: `onResult`, `onStreamItem`,
  `onStreamEnd`, `onError`, `onFlowCredit`, `onNewCommand`.
- Pure state ⇒ trivially testable with deterministic step sequences.

### 6.2 `StreamLink` (`src/core/link.ts`) — ≈ `StreamLink`/`MsgLink`

Pairs the two halves of a sub-channel, forwards `ml_send`/`ml_recv`, tracks
`endHere`/`endThere`/`endBoth`, and detaches from the core when both ends close.

### 6.3 `Msg` / `MsgResult` (`src/core/msg.ts`) — ≈ `msg.py`

Envelopes a single call: command path, args/kw, in/out stream-state machines,
flow-control counters, and result storage. `MsgResult` is the list+dict hybrid
(positional + keyword) returned to callers and streamed items.

### 6.4 Dispatch (`src/dispatch/`)

- `MsgHandler`: resolve `cmd_<name>` / `stream_<name>` / `sub_<name>`, plus the
  built-in `dir_`, `doc_`, `rdy_` meta commands. Match Python's `handle()`
  precedence exactly (doc_ → rdy_ → sub_ → cmd_ → stream_ → `NoCmd`).
- `MsgSender` + `Caller`: the client side. `Caller` is **both** thenable
  (`await sender.cmd("foo", 42)`) and an async-iterable/context-manager for
  streaming (`for await (const m of sender.cmd("bar")) { … }`), mirroring the
  Python `Caller` dual awaitable + `async with` semantics.

### 6.5 Sans-IO boundary contract

The core never awaits. The async adapter turns core callbacks into
Promises/AsyncIterators and turns user Promises into outbound frames pushed
through `core`. This is the seam that keeps the protocol logic reusable across
Node, workers, and (eventually) browsers.

## 7. Public TypeScript API (sketch)

```ts
// server
const srv = new RpcServer({ codec: moatCbor });
srv.register("ping", async (msg) => { await msg.result("pong"); });
srv.register("range", async (msg) => {
  for await (const n of msg) { /* echo */ await msg.send(n * 2); }
});
await srv.listen({ transport: "ws", port: 8080 });

// client
const cli = await Rpc.connect("ws://localhost:8080");
const pong = await cli.cmd("ping");            // MsgResult
const stream = cli.cmd("range", 1, 2, 3);
for await (const m of stream) console.log(m[0]);
```

Exact names/signatures finalised during implementation; the shape mirrors
`MsgSender.cmd` / `Caller`.

## 8. Async client/server example

`examples/client.ts` and `examples/server.ts` demonstrate:

- A WS server exposing a few `cmd_*` and `stream_*` handlers.
- A WS client issuing a simple call and a bidirectional stream.
- A TCP variant showing incremental CBOR framing.
- Runnable via `make example` (boots the server, runs the client, prints
  results, exits 0).

## 9. Test plan

Tooling: **Vitest** (fast, ESM-native, mocks), plus **fast-check** for property
tests and **tsx** to run TS interop scripts.

- **Unit** (`test/unit/`): header pack/unpack (incl. sign flip & edge ids),
  flag reconstruction, `push_kw`/`pop_kw` disambiguation, error-code →
  exception mapping, `Path` tag 39 round-trip, proxy/error marshal (tags
  27/32769), `RpcCore` state-machine step sequences (feed → assert drains &
  callbacks).
- **Property** (`test/property/`): random (id, flag) ↔ wire int round-trips;
  random arg/kw combos ↔ CBOR bytes ↔ parsed; random path trees.
- **Golden vectors** (`test/golden/` + `test/fixtures/*.cbor`): a curated set of
  (Python-produced) byte blobs with expected decoded forms; `golden-gen.py`
  regenerates them from the Python library so drift is caught. Covers: simple
  call, reply, error, warning+flow-control, streamed items, kwargs
  disambiguation, tagged Path/Set/Date/error.
- **Loopback** (`test/loopback/`): TS↔TS end-to-end over an in-memory duplex,
  over a real localhost WebSocket, and over a localhost TCP socket — exercises
  the full async adapter.
- **Interop** (`test/interop/`): TS↔Python. A Vitest fixture spawns a Python
  process (using the repo's `moat.lib.rpc` + `moat.lib.stream`) as either
  client or server, and the TS side as the peer, over (a) WebSocket and (b) raw
  TCP, asserting identical behaviour for: simple call, error forwarding,
  cancellation, bidirectional streaming, flow control, and `dir_`/`doc_`.
  Reverse direction (Python client → TS server) is also covered. Python is
  invoked from the repo venv; the fixture skips gracefully if Python/the venv
  is unavailable.

All test output is redirected to temp files (per repo norms) for analysis.

## 10. NPM packaging

`package.json` highlights:

- `"name": "moat-lib-rpc"`, `"version": "0.1.0"` (semver; 0.x patch auto via
  CI tag), `"type": "module"`, `"license": "GPL-3.0-or-later"`.
- Dual ESM + CJS build with a `exports` map (`import`/`require`/`types`), plus
  subpath exports mirroring `cbor2` (`./codec`, `./transport/ws`, …).
- `"engines": { "node": ">=20" }`, `"sideEffects": false` (tree-shakeable).
- `"main"`, `"module"`, `"types"`, `"files": ["dist", "README.md", "LICENSE"]`.
- `"publishConfig": { "provenance": true, "access": "public" }` (npm
  provenance from CI).
- Scripts: `build`, `test`, `test:interop`, `lint`, `format`, `min`, `example`,
  `prepublishOnly`.
- Dependencies: `cbor2`. Dev deps: `typescript`, `vitest`, `@vitest/coverage`,
  `fast-check`, `tsup`, `esbuild`, `eslint`, `prettier`, `tsx`, `ws` (+
  `@types/ws`).

## 11. Tooling & CI

- **Build:** `tsup` (orchestrates ESM + CJS + dts via `tsc --emitDeclarationOnly`),
  `esbuild` for the minified browser/standalone bundle.
- **Lint/format:** ESLint flat config + Prettier; `make lint`.
- **CI (`.github/workflows/ts-msg-rpc.yml`):** install, lint, typecheck
  (`tsc --noEmit`), unit + property + loopback tests, golden-vector check,
  interop tests (sets up the Python venv), `npm pack --dry-run`, and on tag →
  `npm publish --provenance`.
- **Typechecking:** strict `tsconfig` (`strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`); the package ships `.d.ts`.

## 12. Makefile (`ts/msg/moat-lib-rpc/Makefile`)

Standard targets (idiomatic for the repo, independent of the Python `mt`):

- `make install` — `npm ci`.
- `make build` — `npm run build` (ESM + CJS + types into `dist/`).
- `make min` — produce `dist/moat-lib-rpc.min.js` (esbuild, terser-gzip-sized
  banner) + a `.min.js.map`.
- `make test` / `make test:interop` — run Vitest suites.
- `make lint` / `make fmt` / `make typecheck`.
- `make example` — boot server + run client example.
- `make pack` — `npm pack` (dry-run-safe) into `dist/`.
- `make publish` — guarded `npm publish --provenance` (requires `NPM_TOKEN`).
- `make clean` — remove `dist/`, coverage, build caches.

`make min` is the headline minification target requested.

## 13. Release to npmjs.org

- Versions derived from git tags (`v0.x.y`) in CI; the workflow publishes on
  tag push with npm provenance (Sigstore).
- `README.md` documents the `npm install moat-lib-rpc` quick-start.
- First release `0.1.0`; remain `0.x` until the wire-core + interop are stable,
  then `1.0.0`.

## 14. Risks & decisions

- **Header scheme drift:** the README's "id=1 → 4 / reply -5" disagrees with
  the code's "id=1 → 0 / reply -4". Decision: **follow the code**; golden
  vectors pin this.
- **JS 32-bit bitwise ops:** use arithmetic, not `<<`/`>>`, for the header.
- **`Map` vs plain objects:** use `Map` for CBOR maps everywhere so kwargs
  detection is positional and unambiguous (matches `pop_kw`).
- **`NotGiven`/`undefined`:** `NotGiven` ≡ CBOR `undefined`; never confuse with
  `null`.
- **Strict sans-IO:** the TS core is purer than Python's `HandlerStream` (no
  internal taskgroup). Behaviour is equivalent; the async adapter owns
  scheduling. This is a deliberate, documented divergence.
- **Scope honesty:** "same features" is delivered in phases; phase 1 is the
  wire-compatible core + interop. Auth/nest/alerts/reliable/apps are follow-up
  Beads issues, not blockers for a useful, publishable package.

## 15. Milestones / steps

1. Scaffold package, configs, Makefile stub, CI skeleton; `make build` green.
2. `const.ts`, `errors.ts`, `wire.ts` + unit/property tests + golden generator.
3. `codec.ts` + `path.ts` + `proxy.ts` with tag table; golden vector tests pass.
4. `core/` (handler, link, msg) — sans-IO state machine + unit tests.
5. `dispatch/` (handler, sender, caller) + loopback tests (TS↔TS).
6. `transport/` (ws, tcp, pipe, framing) + async adapter; loopback over WS/TCP.
7. `examples/` + `make example`.
8. Interop suite (TS↔Python) over WS and TCP; fix drift; lock golden vectors.
9. Minified build (`make min`), `npm pack` dry-run, provenance publish workflow.
10. README + docs; cut `0.1.0`; create phase-2 follow-up Beads issues.

## 16. Future / out of scope (follow-up issues)

- Auth (Diffie–Hellman handshake, `moat.lib.diffiehellman`).
- `rpc_on_rpc` nesting (`nest.py`).
- Alert propagation (`alert.py`).
- `Reliable*` lossy-medium wrapper.
- Full command-tree framework (`RootCmd`/`DirCmd`/layered/listening cmds) and
  the `app/*` catalogue.
- Browser/WASM build & CDN bundle.
- Auto-generated proxy bindings (cf. existing `moat-8sn`).

## 17. Open questions

- Confirm the preferred npm org/scope: plain `moat-lib-rpc` vs a `@moat/...`
  scoped name (affects `package.json` + publish config).
- Should the browser ESM build be a phase-1 deliverable or deferred?
- License: repo is GPL-3.0-or-later; `cbor2` is MIT (compatible). Confirm GPL
  for the published package is acceptable to the maintainer.
