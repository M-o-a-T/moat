# Plan: `@moat/lib-rpc` — TypeScript port of `moat.lib.rpc`

Status: **Planning** (no code yet). Tracks Beads epic **`moat-ad2`**.
Package location: `ts/moat-lib-rpc/` (package name `@moat/lib-rpc` on npm).
Related follow-up issues: **`moat-ad2.1`** (Python WebSocket transport),
**`moat-p5m`** (move `moat/nodered` to `js/`).

## 1. Goal

Create a modern, publishable TypeScript/JavaScript NPM package that is a faithful
port of MoaT's Python `moat.lib.rpc` library. It must speak the **same wire
protocol** so that a TS client/server interoperates byte-for-byte with a Python
client/server. The library core follows **sans-IO** principles; a thin async
adapter provides a nice client/server UX. The package must ultimately run in the
**browser** (web frontend), which drives the phasing below.

Mirrored capabilities, phased:

- **Phase 1 — wire-compatible core (no streaming):** request/response RPC with
  asynchronous replies; cancellation (server-initiated on the wire; a client
  "cancel" of a non-streaming call is local-only, see §4.8) and
  exception forwarding; hierarchical, path-addressed command dispatch
  (`cmd_*` / `sub_*`); built-in meta commands `dir_`, `doc_`, `rdy_`; CBOR
  codec (`cbor2`) with MoaT's standard extension tags; WebSocket and TCP
  transports; TS↔Python interop.
- **Phase 2 — browser + streaming + auth:** a browser ESM build; bidirectional
  streaming over a single sub-channel with flow control; the Diffie–Hellman
  auth handshake (requires streaming).
- **Phase 3 — the rest:** `rpc_on_rpc` nesting, alert propagation, the
  `Reliable*` lossy-medium wrapper, the full command-tree/`app/*` framework, and
  a subset `moat.link.client` (especially receiving data / subscribing to
  updates). See §16.

## 2. Non-goals (for this plan)

- Porting the MicroPython/embedded variants.
- Porting `moat.link`, `moat.micro`, or any `app/*` device drivers (i2c, spi,
  fs, net, …). Those are consumers of this library, not part of it.
- Designing a new wire protocol. We mirror the existing one exactly.

## 3. Directory layout

The package root is `ts/moat-lib-rpc/` (no intermediate layer). Plain-JS
packages live under a separate top-level `js/` directory (see follow-up
`moat-p5m`, which relocates `moat/nodered` there).

```
ts/moat-lib-rpc/
  PLAN.md                      # this file
  package.json               # npm metadata, exports map, scripts
  tsconfig.json              # strict TS, ESM, declarations
  tsconfig.build.json        # build-only (excludes tests)
  README.md                  # synopsis + main (Myst-friendly)
  LICENSE                   # MIT (compatible with cbor2)
  Makefile                   # build / minify / test / publish targets
  eslint.config.js           # ESLint flat config
  .prettierrc                # format config
  .gitignore                 # node_modules, dist, *.tsbuildinfo, coverage
  src/
    index.ts                 # public barrel + re-exports
    const.ts                 # B_*, E_*, S_*, SD_* constants
    errors.ts                # StreamError taxonomy + decodeStreamError()
    wire.ts                  # i_f2wire / wire2i_f header packing (bitwise shifts)
    codec.ts                 # cbor2 wiring + MoaT tag table
    path.ts                  # Path type (encode/decode tag 39, optional)
    proxy.ts                 # Proxy/DProxy + error marshalling (tags 27/32769)
    core/
      handler.ts             # RpcCore — sans-IO multiplexer (≈ HandlerStream)
      link.ts                # StreamLink (≈ MsgLink / StreamLink)
      msg.ts                 # Msg envelope + MsgResult (≈ Msg/MsgResult)
    dispatch/
      handler.ts             # MsgHandler base (cmd_/sub_, dir_/doc_/rdy_)
      sender.ts              # MsgSender + Caller (thenable; streaming in P2)
      tree.ts                # minimal RootCmd/DirCmd (stretch)
    transport/
      ws.ts                  # WebSocket client/server (binary frames = CBOR)
      tcp.ts                 # raw TCP client/server (incremental CBOR)
      pipe.ts                # stdin/stdout driver (for interop tests)
      framing.ts             # incremental cbor2 decoder helper
    async/
      adapter.ts             # sans-IO core <-> Promises/AsyncIterators
                             # (Caller lives in dispatch/sender.ts)
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
has drifted; where it disagrees with the code, the **code wins**. The TS port
reproduces the code's behaviour exactly.

### 4.1 Framing / transport

- Each RPC message is one **CBOR array**.
- Over **WebSocket**: one CBOR array per **binary** WS frame
  (`send = ws.send(Buffer.from(codec.encode(msg)))`;
  `recv = codec.decode(await ws.nextBinary())`). Text WS frames are **not** used
  by RPC — they are reserved for serialized HTML/XML (DOM objects) on the Python
  side (see follow-up `moat-ad2.1`). The TS WS transport only emits/consumes
  binary frames and ignores/tears-down on unexpected text frames.
- Over **raw TCP / USB**: CBOR arrays streamed back-to-back with **no length
  prefix**; CBOR is self-delimiting. Decode incrementally, feeding bytes to a
  streaming decoder and extracting one array at a time. **No `msg_prefix`
  byte** — we do not multiplex console data onto the RPC stream.
- Messages are **reliable, ordered**. Lossy/reordering media require the
  `Reliable*` wrapper (phase 3).

### 4.2 Header integer packing

Defined in `moat/lib/rpc/stream/base.py`:

```python
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

**Bitwise shifts, matching Python:** JS `<<`/`>>`/`&` coerce to signed 32 bits,
which could overflow at id > 2²⁹. However, IDs are recycled, so the number of
in-flight requests stays far below that threshold. Bitwise shifts mirror
Python's implementation exactly:

```ts
function i_f2wire(id: number, flag: number): number {
  // assert id !== 0; 0<=flag<=3 || flag===7
  if (id > 0) id -= 1;
  return (id << 2) | (flag & 3);
}
function wire2i_f(w: number): [number, number] {
  const f = w & 3;
  let id = w >> 2;
  if (id >= 0) id += 1;
  return [id, f];   // caller then does i = -i
}
```

Example round-trip (verified against the code): originator id=1, flag=0 →
wire `0`; responder decodes `(1,0)` → flips to `-1`; reply with id=-1, flag=0
→ wire `-4`; originator decodes `(-1,0)` → flips to `1`. ✅

### 4.3 ID allocation and the reuse delay (important)

Originator maintains **tiered free-id pools** (`<6`, `<64`, rest — small ids
encode to fewer CBOR bytes) and allocates from the smallest tier first;
otherwise a counter (starting at 1) is incremented. An id may be reused only
after **both** directions have sent their final (stream-bit-clear) message.

**The reuse delay must be preserved.** In its `L` (CPython/large) build — the
peer we interop with — Python delays recycling a freed id by ~1 second before
returning it to the pool (`HandlerStream._dly`); this avoids races where a
late in-flight message for the just-closed id collides with a freshly reused
one. (The small/MicroPython build recycles immediately.) The TS core
replicates the `L` behaviour: freed ids enter a single holding queue and are
returned to the tiered pools only after the delay (implemented in the async
adapter, since the sans-IO core has no clocks — see §6.5). Wire compatibility
only requires uniqueness-while-live, but the delay is required for
correctness.

### 4.4 Flags (low 2 bits of the header)

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
(the codec appends an empty `{}` to disambiguate — see §4.7). Flow control and
warnings are **phase 2** (streaming); phase 1 only *sends* flags 0 and 2 but
must tolerate receiving the others: a stream-flagged request gets an
`E_NO_STREAM` error reply (Python's `NoStream` path), warnings are logged and
dropped.

### 4.5 Stream states & directions (phase 2)

From `const.py`: `S_NEW=4`, `S_ON=5`, `S_OFF=6`, `S_END=3` (per direction,
tracked separately for in/out); `SD_NONE=0`, `SD_IN=1`, `SD_OUT=2`, `SD_BOTH=3`.
The phase-2 `Msg` port tracks `_streamIn` / `_streamOut` with the transitions
documented in `msg.py`. An interaction is complete when **both** directions
reach `S_END` (each side sent exactly one stream-bit-clear message). Phase 1
only ever uses `S_NEW → S_END` (single final message each way).

### 4.6 Error codes & taxonomy

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
`SkippedData`, `MustStream`, `WantsStream`, `RemoteError`, `NotReadyError`,
`Short/LongCommandError`) plus a `Flow` signal object (phase 2; not thrown,
surfaced via the flow-control callback).

Note that an **unknown command** is *not* signalled with `E_NO_CMD` on the
wire: Python's `handle()` raises `KeyError`, which is marshalled like any
other exception (tag 27, `["_rErr", "KeyError", …]`). `[E_NO_CMD]` is only
sent when the stream has no command handler at all. Golden vectors pin both
behaviours.

### 4.7 Payload conventions

- A message array is `[header, *args, ?kwargsMap]`.
- **First** message of a call (incoming side): `[header, cmdPath, *args, ?kw]`.
  On the wire `cmdPath` is a **plain array** of path elements — Python's
  `HandlerStream.handle()` sends `msg.rcmd` re-reversed, i.e. a plain list,
  *not* a tag-39 `Path` (tag 39 only appears for `Path` values nested in
  payloads). The TS port sends a plain array too (byte parity) and on decode
  accepts array, tag-39 `Path`, or string; an empty args tail defaults to the
  empty path (`msg_in`: `cmd = a.pop(0) if a else Path()`).
- Subsequent messages: `[header, *args, ?kw]`.
- **kwargs** use `moat.util.pp.push_kw` / `pop_kw`:
  - Encode (`push_kw`): append the kwargs `Map` to the args array iff (a) kwargs
    is non-empty, **or** (b) the last positional arg is itself a `Map`, **or**
    (c) it is a user warning consisting of a single integer (append `{}`). The
    trailing map is otherwise omitted.
  - Decode (`pop_kw`): if the last array element is a `Map`, pop and treat as
    kwargs; else `{}`.
  - The TS port uses `Map` for all CBOR maps on the wire path so kwargs vs.
    positional-map disambiguation is positional and unambiguous. **Do not rely
    on cbor2's defaults** — set the map-decoding option explicitly and
    unit-test that string-keyed maps decode to `Map`. (The kwargs map may be
    converted to a plain object at the public API boundary for ergonomics.)
- **Sentinels:** `NotGiven` ≡ `Ellipsis` → CBOR `undefined` (0xF7). `true`/
  `false`/`null` map naturally. Booleans must be emitted as CBOR bool (not
  int 0/1).
- **Bytes vs text:** CBOR byte strings → `Uint8Array`; CBOR text → `string`.
  The codec must preserve the distinction (paths may contain `Uint8Array`
  elements).

### 4.8 Lifecycle / exchange rules

- Originator allocates a fresh positive id, sends the command (flag 0 in phase 1).
- Responder decodes, flips sign, dispatches by path, and replies using the
  (negative) id. Exactly one stream-bit-clear message must be sent in each
  direction; the interaction ends when both are delivered.
- **Cancellation:** the responder cancels by sending `[E_CANCEL]` with
  `B_ERROR` as its final message. The originator of a *non-streaming* call
  cannot cancel on the wire — its direction is already closed after the
  initial flag-0 message (`Msg.kill()` is a no-op once `set_end()` ran); a
  client-side cancel merely abandons the call locally and the eventual reply
  is dropped as "late". Wire-level client cancel needs an open outgoing
  direction, i.e. streaming (phase 2).
- (Phase 2) Streaming: the originator may not send streamed data before
  receiving the initial reply with the stream bit set. Initial and final
  messages are out-of-band. Warnings (flag 3) attach conceptually to the
  following message.
- Late/extra messages after `S_END` are logged and dropped (matches `ml_recv`).

## 5. Codec strategy (`cbor2`)

### 5.1 Choice

Use the npm package **`cbor2`** (v2.3.0, MIT, hildjj/cbor2) — RFC 8949,
ESM/CJS, custom `Tag` handling, and a streaming decoder for incremental TCP
decode. (The Node-RED codec package — now `@moat/meta-codec` under
`js/moat-meta-codec/` — likewise switched to `cbor2`; see issue `moat-p5m`.)

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

### 5.3 `Path` type (`src/path.ts`) — tag 39 is optional

- Immutable, backed by an array of elements (`string | number | bigint |
  boolean | null | Uint8Array | Path`).
- **Encode:** `Path` *values* (in args/kw) emit `new Tag(39, elements)`,
  mirroring `_enc_path` — which uses `raw_rooted`: a rooted path carries its
  `RootPath` prefix as the first element, itself encoded as a tag-32769 proxy
  such as `"R"`. The **command slot** of a call's first message is sent as a
  plain array (§4.7).
- **Decode:** accept **either** tag 39 **or** a plain array. When the command
  path slot (or any path-bearing field) is a plain array, build the `Path` from
  it directly. This tolerates peers/older firmware that send paths untagged.
  Tolerate a leading root proxy on decode (mirrors
  `Path.build(val, decoded=True)`); full `RootPath` semantics arrive with the
  phase-3 `moat.link.client` subset.
- Support `build()`, `raw`, `parent`, concatenation, and the slash/dot string
  forms needed for logging and tests. (Full parser fidelity is stretch; the wire
  only needs the array form.)

### 5.4 Proxy / error marshalling (`src/proxy.ts`)

- Maintain a name⇆constructor registry mirroring `moat.lib.proxy`.
- **Pre-register the standard error proxy names** so interop reconstructs
  concrete exception types instead of degrading everything to `RemoteError`:
  `_rErr`, `_CSMErr`, `_CSDErr`, `_CNsErr`, `_CNCsErr`, `_CNCErr`, `_CWSErr`,
  `_CMSErr`, `_NRdyErr`, `_SCmdErr`, `_LCmdErr` (cf. `moat/lib/rpc/errors.py`),
  plus the `moat.lib.codec.errors` proxies and the root-path proxies (`"R"`,
  `_P…`).
- Encode an `Error`: prefer a registered proxy name under tag 32769; else emit
  tag 27 `["_rErr", errorClassName, ...args]` (matches `enc_any`'s exception
  fallback). Decode reverses both, reconstructing an `RpcError` subtype when
  the class is unknown.
- `DProxy` (tag 27) round-trips `[name, *args, ?kw]` for opaque objects.

### 5.5 Incremental decode for TCP

Use `cbor2`'s streaming decoder fed by socket `'data'` events; emit one decoded
array per complete CBOR object. No `msg_prefix` handling.

## 6. Sans-IO core architecture

The Python `HandlerStream` is labelled sans-IO but internally uses taskgroups
and queues. The **TS core is stricter**: a pure, synchronous state machine with
**no promises, timers, or I/O**. Async behaviour lives entirely in the
`transport/` + `async/` layers.

### 6.1 `RpcCore` (`src/core/handler.ts`) — ≈ `HandlerStream`

- Holds the live sub-channel map (`id → StreamLink`), the id allocator, and
  (phase 2) per-direction credit counters.
- **Inputs (sync):** `core.feed(message: unknown[]): void` — decode header,
  flip sign, route to an existing `StreamLink` or spawn a new one and invoke
  the registered command handler.
- **Outputs (sync):** `core.drain(): unknown[][]` returns queued outbound
  frames (pull-based; composes best with deterministic sans-IO tests). The
  async adapter pumps these to the transport.
- **Callbacks** the core invokes on the adapter: `onResult`, `onError`,
  `onNewCommand`, and (phase 2) `onStreamItem`, `onStreamEnd`, `onFlowCredit`.
- Pure state ⇒ trivially testable with deterministic step sequences.

### 6.2 `StreamLink` (`src/core/link.ts`) — ≈ `StreamLink`/`MsgLink`

Pairs the two halves of a sub-channel, forwards `ml_send`/`ml_recv`, tracks
`endHere`/`endThere`/`endBoth`, and detaches from the core when both ends close
(detachment triggers the reuse-delay hold, §4.3).

### 6.3 `Msg` / `MsgResult` (`src/core/msg.ts`) — ≈ `msg.py`

Envelopes a single call: command path, args/kw, result storage, and (phase 2)
in/out stream-state machines and flow-control counters. `MsgResult` is the
list+dict hybrid (positional + keyword) returned to callers. Phase 1 supports
only the single-result (non-streaming) lifecycle.

### 6.4 Dispatch (`src/dispatch/`)

- `MsgHandler`: resolve `cmd_<name>` / `sub_<name>`, plus the built-in `dir_`,
  `doc_`, `rdy_` meta commands. Match Python's `handle()` order exactly:
  empty path (direct `cmd`/`stream`, else `ShortCommandError`) → `doc_` →
  leaf `cmd_X`/`stream_X` → `rdy_` readiness check → `sub_X` recursion →
  rdy-fallback `result(None)` → `KeyError` (marshalled as `_rErr`, §4.6).
  Note `doc_`/`rdy_`/`dir_` match at the **end** of the path (`rcmd[0]` of the
  reversed list); the `rdy_` check is `L`-gated in Python — phase 1 implements
  the trivial "answer `None`" fallback. `stream_` handlers arrive in phase 2.
- `MsgSender` + `Caller`: the client side. In phase 1 `Caller` is a **thenable**
  (`await sender.cmd("foo", 42)`). The async-iterator / context-manager
  streaming surface (`for await (const m of sender.cmd("bar")) { … }`) lands in
  phase 2.

### 6.5 Sans-IO boundary contract (and the reuse delay)

The core never awaits and has no clock. The async adapter turns core callbacks
into Promises/AsyncIterators and turns user Promises into outbound frames
pushed through `core`. The **reuse delay** (§4.3) is owned by the adapter: when
the core detaches a link, the adapter appends `(id, now)` to a single holding
queue with **one** scheduled — and, on Node, `unref()`ed — timeout (not one
timer per id, which would keep the event loop alive) and only then returns
the id to the core's free pools. This keeps the core pure while preserving
the race-avoidance behaviour Python relies on.

## 7. Public TypeScript API (sketch)

```ts
// server
const srv = new RpcServer({ codec: moatCbor });
srv.register("ping", async (msg) => { await msg.result("pong"); });
await srv.listen({ transport: "ws", port: 8080 });

// client
const cli = await Rpc.connect("ws://localhost:8080");
const pong = await cli.cmd("ping");            // MsgResult
```

(Phase 2 adds `for await (const m of cli.cmd("range", 1, 2, 3)) { … }`.)
Exact names/signatures finalised during implementation; the shape mirrors
`MsgSender.cmd` / `Caller`.

## 8. Async client/server example

`examples/client.ts` and `examples/server.ts` demonstrate a WS server with a few
`cmd_*` handlers and a WS client issuing a simple call, plus a TCP variant
showing incremental CBOR framing. Runnable via `make example` (boots the server,
runs the client, prints results, exits 0). A streaming example is added in
phase 2.

## 9. Test plan

Tooling: **Vitest** (fast, ESM-native, mocks), **fast-check** for property
tests, **tsx** to run TS interop scripts.

- **Unit** (`test/unit/`): header pack/unpack (incl. sign flip & edge ids),
  flag reconstruction, `push_kw`/`pop_kw` disambiguation, error-code →
  exception mapping, `Path` tag 39 round-trip (and plain-array tolerance),
  proxy/error marshal (tags 27/32769), `RpcCore` state-machine step sequences
  (feed → assert drains & callbacks).
- **Property** (`test/property/`): random (id, flag) ↔ wire int round-trips;
  random arg/kw combos ↔ CBOR bytes ↔ parsed; random path trees.
- **Golden vectors** (`test/golden/` + `test/fixtures/*.cbor`): a curated set of
  (Python-produced) byte blobs with expected decoded forms; `golden-gen.py`
  regenerates them from the Python library so drift is caught. Covers: simple
  call, reply, error, kwargs disambiguation, tagged/plain Path, Set, Date,
  error marshal, unknown-command `KeyError`, and float width parity (Python
  emits shortest-lossless floats f16→f32→f64; configure cbor2 to match and pin
  e.g. `1.5`, `0.1`, `NaN`). (Warnings/flow/streamed items added in phase 2.)
- **Loopback** (`test/loopback/`): TS↔TS end-to-end over an in-memory duplex,
  over a real localhost WebSocket, and over a localhost TCP socket — exercises
  the full async adapter.
- **Interop** (`test/interop/`): TS↔Python. A Vitest fixture spawns a Python
  process (using the repo's `moat.lib.rpc` + `moat.lib.stream`) as either
  client or server, and the TS side as the peer, over (a) WebSocket and (b) raw
  TCP, asserting identical behaviour for: simple call, error forwarding,
  server-initiated cancellation, and local abandonment of a call (client-side
  "cancel", §4.8). Reverse direction (Python client → TS server) is also
  covered, including a Python *streaming* request against the phase-1 TS
  server (expect `E_NO_STREAM`). (Full streaming/flow-control interop is added
  in phase 2, once the Python WS transport `moat-ad2.1` is available.) Python
  is invoked from the repo venv, which always provides `moat.lib.rpc`.

## 10. NPM packaging

`package.json` highlights:

- `"name": "@moat/lib-rpc"`, `"version": "0.1.0"` (semver; 0.x patch auto via
  CI tag), `"type": "module"`, `"license": "MIT"`.
- The `@moat` scope appears available (no npm user/org named "moat": both
  `registry.npmjs.org/-/org/moat` and `/-/user/moat` return 404, and a
  `scope:moat` search returns zero hits). **Action:** register the `@moat` org
  on npmjs.org before first publish.
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
  `esbuild` for the minified bundle.
- **Lint/format:** ESLint flat config + Prettier; `make lint`.
- **CI (`.github/workflows/ts-moat-lib-rpc.yml`):** install, lint, typecheck
  (`tsc --noEmit`), unit + property + loopback tests, golden-vector check,
  interop tests (sets up the Python venv), `npm pack --dry-run`, and on tag →
  `npm publish --provenance`.
- **Typechecking:** strict `tsconfig` (`strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`); the package ships `.d.ts`.

## 12. Makefile (`ts/moat-lib-rpc/Makefile`)

Standard targets (idiomatic for the repo, independent of the Python `mt`):

- `make install` — `npm ci`.
- `make build` — `npm run build` (ESM + CJS + types into `dist/`).
- `make min` — produce `dist/moat-lib-rpc.min.js` (esbuild, terser-gzip-sized
  banner) + a `.min.js.map`.
- `make test` / `make test-interop` — run Vitest suites (no colon in target
  names; GNU make reserves it. The *npm script* may still be `test:interop`).
- `make lint` / `make fmt` / `make typecheck`.
- `make example` — boot server + run client example.
- `make pack` — `npm pack` (dry-run-safe) into `dist/`.
- `make publish` — guarded `npm publish --provenance` (requires `NPM_TOKEN`).
- `make clean` — remove `dist/`, coverage, build caches.

`make min` is the headline minification target requested.

## 13. Phasing

### Phase 1 — wire-compatible core (no streaming)
Request/response, error forwarding, server-side cancellation (§4.8),
hierarchical dispatch
(`cmd_`/`sub_` + `dir_`/`doc_`/`rdy_`), `cbor2` codec with MoaT tags, optional
tag-39 Path, WS + TCP transports, sans-IO core + async adapter (with reuse
delay), TS↔TS loopback and TS↔Python interop (non-streaming), minified build,
`npm pack`, publish `0.1.0`.

### Phase 2 — browser + streaming + auth
Browser ESM build + browser WebSocket transport; streaming state machines in
`Msg` (`S_*`/`SD_*`); flow control (credits, `E_SKIP`, flow warnings,
`B_WARNING_INTERNAL` reconstruction); `Caller` async-iterator /
context-manager streaming API; the Diffie–Hellman auth handshake (mirrors
`moat.lib.rpc.auth` + `moat.lib.diffiehellman`); streaming/flow-control
interop tests (needs Python WS transport `moat-ad2.1`).

### Phase 3 — the rest
`rpc_on_rpc` nesting (`nest.py`); alert propagation (`alert.py`); the
`Reliable*` lossy-medium wrapper; the full command-tree framework
(`RootCmd`/`DirCmd`/layered/listening cmds) and the `app/*` catalogue; and a
**subset `moat.link.client`** — especially receiving data / subscribing to
updates (watch/`d.walk`/`d.watch`).

## 14. Risks & decisions

- **Header scheme drift:** the README's "id=1 → 4 / reply -5" disagreed with
  the code's "id=1 → 0 / reply -4" (fixed in the README, commit `e9d2823a8`);
  golden vectors pin the code's behaviour.
- **Header packing uses bitwise shifts** (`(id << 2) | (flag & 3)`, `w >> 2`):
  mirrors Python exactly. JS 32-bit coercion could overflow at id > 2²⁹, but
  IDs are recycled so in-flight counts stay far below that threshold.
- **Reuse delay kept:** ~1 s hold before recycling freed ids (mirrors Python's
  `L` build; the small build recycles immediately), replicated in the async
  adapter via a single unref'ed timer, to avoid late-message races. Not
  optional. Id pools are tiered (`<6`, `<64`, rest) like Python's.
- **`Map` vs plain objects:** use `Map` for CBOR maps on the wire path so
  kwargs detection is positional and unambiguous (matches `pop_kw`); configure
  cbor2's map handling explicitly rather than trusting defaults.
- **`NotGiven`/`undefined`:** `NotGiven` ≡ CBOR `undefined`; never confuse with
  `null`.
- **Path tag 39:** tag `Path` *values* on send; the command slot is a plain
  array (matching Python's bytes, §4.7); accept tagged or plain on decode.
- **No `msg_prefix`:** RPC owns its stream; no console multiplexing.
- **Strict sans-IO:** the TS core is purer than Python's `HandlerStream` (no
  internal taskgroup); the async adapter owns scheduling and the reuse-delay
  timer. Documented, deliberate divergence.
- **License MIT.** The repo is **LGPL v3**, and this package is a port
  (derivative work) of the Python library — publishing under MIT is a
  deliberate relicensing by the copyright holder, not a mere compatibility
  question (the MIT `cbor2` dependency imposes nothing). Check for third-party
  contributions to `moat.lib.rpc` before the first release.
- **Scope honesty:** "same features" is delivered in phases; phase 1 is the
  non-streaming wire-compatible core + interop. Streaming/auth/browser are
  phase 2; the broader framework and `moat.link.client` subset are phase 3.

## 15. Milestones / steps (phase 1)

1. Scaffold package, configs, Makefile stub, CI skeleton; `make build` green.
2. `const.ts`, `errors.ts`, `wire.ts` + unit/property tests + golden generator.
3. `codec.ts` + `path.ts` + `proxy.ts` with tag table (tag 39 optional);
   golden vector tests pass.
4. `core/` (handler, link, msg — non-streaming) — sans-IO state machine +
   unit tests; async adapter with reuse delay.
5. `dispatch/` (handler, sender, caller — thenable) + loopback tests (TS↔TS).
6. `transport/` (ws, tcp, pipe, framing); loopback over WS/TCP.
7. `examples/` + `make example`.
8. Interop suite (TS↔Python) over WS and TCP (non-streaming); fix drift; lock
   golden vectors.
9. Minified build (`make min`), `npm pack` dry-run, provenance publish workflow.
10. Register `@moat` org on npm; README + docs; cut `0.1.0`; file phase-2/3
    follow-up Beads issues.

## 16. Follow-up issues (filed)

- **`moat-ad2.1`** — Python WebSocket transport for `moat.lib.stream`
  (`StackedBlk`-shaped; binary frames = CBOR, text frames reserved for
  serialized HTML/XML DOM). Blocks phase-2 WS interop.
- **`moat-p5m`** — Move `moat/nodered` to `js/` and refresh (switch to `cbor2`,
  align with the `@moat` scope, bring packaging/tests in line with this
  package).

## 17. Remaining open question

- Register the `@moat` organization on npmjs.org before first publish (the
  scope appears free today). Everything else (browser build, license, scope,
  streaming/auth placement) is decided above.
