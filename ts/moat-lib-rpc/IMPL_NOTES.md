# Implementation Notes: `@moat/lib-rpc` TypeScript Port

This document is the implementation reference for the TypeScript port of
`moat.lib.rpc`. It supplements `PLAN.md` with details extracted directly from
the Python source. Together with `PLAN.md`, it provides everything needed to
implement the TS port.

**Source of truth:** the Python code in `moat/lib/rpc/`. Where prose (including
this document) disagrees with the code, the **code wins**.

---

## 1. CBOR Wire Format

### 1.1 Message structure

Every RPC message is a single **CBOR array**:

```
[header, *payload, ?kwargsMap]
```

- `header` (element 0): a CBOR integer encoding the message ID and flags.
- `payload` (elements 1..N-1): positional arguments (CBOR values).
- `kwargsMap` (optional last element): a CBOR map of keyword arguments.

Over **WebSocket**: one CBOR array per binary WS frame. Text frames are not used
by RPC. Over **raw TCP/USB**: CBOR arrays streamed back-to-back with no length
prefix; CBOR is self-delimiting, so feed bytes to a streaming decoder and
extract one array at a time. There is **no `msg_prefix` byte** — RPC owns its
stream.

### 1.2 Header packing (`i_f2wire` / `wire2i_f`)

Defined in `moat/lib/rpc/stream/base.py`:

```python
def i_f2wire(id, flag):
    assert id != 0
    assert 0 <= flag <= 3 or flag == B_WARNING_INTERNAL  # 7
    if id > 0:
        id -= 1
    return (id << 2) | (flag & 3)

def wire2i_f(w):
    f = w & 3
    id = w >> 2
    if id >= 0:
        id += 1
    return (id, f)
```

**Sign convention:** the originator allocates positive IDs (≥ 1). The responder
receives them, flips the sign (`i = -i`), and uses the negative ID in replies.
ID `0` is never sent as a live ID.

**JS port:** uses bitwise shifts exactly as Python does. IDs are recycled, so
the number of in-flight requests stays small — JS 32-bit shift overflow
(> 2²⁹) is never reached:

```ts
function i_f2wire(id: number, flag: number): number {
  if (id > 0) id -= 1;
  return (id << 2) | (flag & 3);
}
function wire2i_f(w: number): [number, number] {
  const f = w & 3;
  let id = w >> 2;
  if (id >= 0) id += 1;
  return [id, f];
  // caller then does: i = -i
}
```

**Round-trip example:** originator `id=1, flag=0` → wire `0`; responder decodes
`(1, 0)` → flips to `-1`; reply `id=-1, flag=0` → wire `-4`; originator decodes
`(-1, 0)` → flips to `1`. ✅

### 1.3 Flags (low 2 bits of header)

| Constant              | Value | Meaning                                      |
|-----------------------|------:|----------------------------------------------|
| (none)                | 0     | Final message for this direction (out-of-band)|
| `B_STREAM`            | 1     | Starts/continues a data stream                |
| `B_ERROR`             | 2     | Terminal error (stream bit clear)             |
| `B_WARNING`           | 3     | Warning / OOB info (= `B_STREAM \| B_ERROR`)  |
| `B_WARNING_INTERNAL`  | 7     | Flow-control warning (reconstructed, see below)|

Only the low 2 bits travel on the wire. `B_WARNING_INTERNAL` (7) is **not**
transmitted distinctly — it is reconstructed on decode: a message with flag `3`
whose payload is a single integer is reclassified as internal flow control
(`flag = 7`). Consequently **user warnings may not consist of a lone integer**
(the codec appends an empty `{}` to disambiguate via `push_kw(is_warn=True)`).

Phase 1 only sends flags 0 and 2 but must tolerate receiving the others:
- A stream-flagged request gets an `E_NO_STREAM` error reply.
- Warnings are logged and dropped.

### 1.4 Message types by flag combination

#### Flag 0 — Final / out-of-band (non-streaming reply or initial request)

**Initial request** (first message of a call, originating side):

```
[header, cmdPath, *args, ?kwargsMap]
```

`cmdPath` is a **plain CBOR array** of path elements — NOT a tag-39 `Path`.
Python's `HandlerStream.handle()` sends `msg.rcmd` re-reversed (i.e. a plain
list). On decode, `msg_in` does `cmd = a.pop(0) if a else Path()` — an empty
args tail defaults to the empty path.

**Reply** (responder, flag 0):

```
[header, *resultArgs, ?kwargsMap]
```

If the handler returns a non-`None` value and hasn't already sent a result,
`HandlerStream._handle` sends `[None]` as the final message:
`await self.send(link, [None], None, 0)`. A handler returning `None` implicitly
sends `[None]` too (the `else` branch in `_handle`).

#### Flag 1 — Stream data (`B_STREAM`)

Subsequent streamed data items. Phase 2 only. Phase 1 treats receipt of this
flag on a new sub-channel as triggering `E_NO_STREAM`.

#### Flag 2 — Error (`B_ERROR`)

Terminal error. Payload encodes the error:

```
[header, errorCode_or_exception, ?kwargsMap]
```

Error encoding cascade (see `MsgLink.ml_send_error`):
1. Try sending the exception object directly: `await ml_send((exc,), None, B_ERROR)`.
2. If that fails, send `(exc.__class__.__name__,) + exc.args`.
3. If that fails, send `(exc.__class__.__name__,)`.
4. If that fails, send `[E_ERROR]` (bare error code `-7`).

On decode, `StreamError.__new__` maps the payload:
- Single integer ≥ 0 → `Flow(n)` (flow control, not a thrown error).
- Single integer < 0 → mapped exception type (see error table below).
- Single `Exception` instance → returned as-is.
- Anything else → `RemoteError`.

#### Flag 3 — Warning (`B_WARNING`)

Non-terminal warning. Attached conceptually to the following message. A lone
integer payload is reclassified as `B_WARNING_INTERNAL` (flag 7).

#### Flag 7 — Internal flow control (`B_WARNING_INTERNAL`, reconstructed)

Carries a `Flow(n)` signal (credit announcement). Not a thrown error. Phase 2.

### 1.5 Error codes and taxonomy

From `const.py` and `errors.py` (`StreamError.__new__`):

| Code        | Value | Mapped exception        | Proxy name  |
|-------------|------:|-------------------------|-------------|
| `E_UNSPEC`  | -1   | `StopMe`                | `_CSMErr`   |
| `E_NO_STREAM`| -2  | `NoStream`              | `_CNsErr`   |
| `E_CANCEL`  | -3   | `CancelledError`        | (builtin)   |
| `E_NO_CMDS` | -4   | `NoCmds`                | `_CNCsErr`  |
| `E_SKIP`    | -5   | `SkippedData`           | `_CSDErr`   |
| `E_MUST_STREAM`| -6 | `MustStream`           | `_CMSErr`   |
| `E_ERROR`   | -7   | `RemoteError`           | `_rErr`     |
| `E_NO_CMD`  | -11  | `NoCmd(E_NO_CMD - m)`   | `_CNCErr`   |

`E_NO_CMD` uses a parameterized scheme: if the error code is `m ≤ E_NO_CMD`,
the exception is `NoCmd(E_NO_CMD - m)`, where the subtraction gives a
sub-command index.

**Important:** An unknown command is **not** signalled with `E_NO_CMD` on the
wire. Python's `handle()` raises `KeyError`, which is marshalled like any other
exception (tag 27, `["_rErr", "KeyError", …]`). `[E_NO_CMD]` is only sent when
the stream has no command handler at all (`HandlerStream._handle` with
`self._sender is None`).

Additional error classes (not wire codes, but marshalled via proxy):
- `NotReadyError` (`_NRdyErr`) — element of command path not ready
- `ShortCommandError` (`_SCmdErr`) — command path too short
- `LongCommandError` (`_LCmdErr`) — command path too long
- `WantsStream` (`_CWSErr`) — `NoStream` called on a streaming endpoint

### 1.6 CBOR tag table (MoaT extensions)

From `moat/lib/codec/_moat_cbor.py` and `moat/lib/proxy/`:

| Tag    | Encodes                          | Wire shape                          |
|--------|----------------------------------|-------------------------------------|
| 39     | `Path` (values only)            | array of path elements             |
| 27     | `DProxy` / wrapped object / error | `[name, *args, ?kw]`              |
| 32769  | `Proxy` (by name)                | string/int name                     |
| 258    | `Set`                            | array                               |
| 1      | `Date` (epoch seconds)           | float                               |
| 0      | `Date` (ISO string) — decode only | string                           |
| 2 / 3  | bignum / neg-bignum             | byte string                         |
| 55799  | self-describe CBOR (passthrough) | —                                   |

### 1.7 Tag 39: Path values vs. command slot

**Path values** (in args/kwargs) emit `Tag(39, elements)` via `_enc_path`, which
calls `Path.raw_rooted`. A rooted path carries its `RootPath` prefix as the
first element, itself encoded as a tag-32769 proxy (e.g. `"R"`).

**Command slot** (first payload element of an initial request) is sent as a
**plain CBOR array** — NOT tag 39. This matches `HandlerStream.handle()` which
sends `msg.rcmd` (a plain list). The TS port must send a plain array too for
byte parity.

**On decode:** accept either tag 39 or a plain array. When the command path slot
(or any path-bearing field) is a plain array, build the `Path` from it directly.
This tolerates peers/older firmware that send paths untagged. Tolerate a leading
root proxy on decode (mirrors `Path.build(val, decoded=True)`).

### 1.8 Payload conventions

#### kwargs packing (`push_kw` / `pop_kw`)

From `moat/util/pp.py`:

**Encode (`push_kw`):** append the kwargs map to the args array iff:
- (a) kwargs is non-empty, **or**
- (b) the last positional arg is itself a `dict`/map, **or**
- (c) it is a user warning consisting of a single integer (append `{}`).

Otherwise the trailing map is omitted.

**Decode (`pop_kw`):** if the last array element is a `Mapping`, pop and treat
as kwargs; else `{}`.

The TS port should use `Map` for all CBOR maps on the wire path so kwargs vs.
positional-map disambiguation is positional and unambiguous. Configure cbor2's
map decoding explicitly; do not rely on defaults.

#### Sentinels

- `NotGiven` ≡ `Ellipsis` → CBOR `undefined` (0xF7). Empty bytes `b""` also
  decodes to `NotGiven` (the codec's `Codec.decode` returns `NotGiven` for
  `b""`).
- `true`/`false`/`null` map naturally. Booleans must be emitted as CBOR bool
  (not int 0/1).

#### Bytes vs text

CBOR byte strings → `Uint8Array`; CBOR text → `string`. The codec must preserve
the distinction (paths may contain `Uint8Array` elements).

### 1.9 Error marshalling via proxy system

From `moat/lib/codec/_moat_cbor.py` (`enc_any`):

1. If the object's type is registered (`obj2name(type(obj))`), emit tag 32769
   with the name, then wrap with `wrap_obj`.
2. If the object itself is registered (`obj2name(obj)`), emit tag 32769 with
   the name directly.
3. If it's an `Exception`, emit tag 27 with `["_rErr", className, *args]`.
4. Fall back to `get_proxy(obj)` (auto-proxy, tag 32769).

Decode reverses both tag 32769 and tag 27, reconstructing an `RpcError` subtype
when the class is known, or a `DProxy` when unknown.

**Pre-register these proxy names** for interop:
`_rErr`, `_CSMErr`, `_CSDErr`, `_CNsErr`, `_CNCsErr`, `_CNCErr`, `_CWSErr`,
`_CMSErr`, `_NRdyErr`, `_SCmdErr`, `_LCmdErr`, plus codec error proxies
(`SilentRemoteError` etc.) and root-path proxies (`"R"`, `_P…`).

---

## 2. ID-Pool Lifecycle

### 2.1 Tiered free-ID pools

The originator maintains three tiers of free-ID sets (`HandlerStream.__init__`):

```python
self._id1: set[int] = set()       # ids < 6
if L:
    self._id2: set[int] = set()   # ids < 64 (L build only)
self._id3: set[int] = set()       # rest
self._id = 0                      # monotonic counter
```

**Allocation** (`_gen_id`): allocate from the smallest tier first:
1. If `_id1` (ids < 6) has a free ID, pop it.
2. Else if `L` and `_id2` (ids < 64) has a free ID, pop it.
3. Else if `_id3` (rest) has a free ID, pop it.
4. Else increment the counter `self._id += 1` and return it.

Small IDs encode to fewer CBOR bytes, so the tiering optimizes wire size.

**Note:** `_id2` only exists in the `L` (large/CPython) build. In the small
(MicroPython) build, there are only two tiers: `<6` and `rest`.

### 2.2 Reuse-delay timer (~1 second)

When a `StreamLink` is detached (both directions ended), its ID is returned to
the pools. In the `L` build, this is **delayed by ~1 second** to avoid races
where a late in-flight message for the just-closed ID collides with a freshly
reused one.

**Detach flow** (`HandlerStream.detach`):

```python
def detach(self, link):
    mid = link.id
    del self._msgs[mid]
    if mid <= 0:
        return  # remote-originated IDs are never recycled

    if L:
        self._dly_q.put_nowait((mid, ticks_ms()))
    else:
        if mid < 6:
            self._id1.add(mid)
        else:
            self._id3.add(mid)
```

**Delay task** (`HandlerStream._dly`):

```python
async def _dly(self):
    while True:
        mid, t = await self._dly_q.get()
        tt = ticks_ms()
        td = ticks_diff(tt, t)
        if td < 1000:
            await sleep_ms(1000 - td)
        if mid < 6:
            self._id1.add(mid)
        elif mid < 64:
            self._id2.add(mid)
        else:
            self._id3.add(mid)
```

Key characteristics:
- **Single timer/queue**, not one timer per ID. The `_dly_q` is a `Queue(999)`.
  Freed IDs enter the queue with a timestamp; the `_dly` task processes them
  sequentially, sleeping only the remaining delay.
- **Only `L` build** has the delay. Small build recycles immediately.
- **Only positive IDs** (originator-allocated) are recycled. Negative IDs
  (responder-allocated, `mid <= 0`) are never returned to pools.
- The tier assignment on recycle uses the same thresholds: `<6` → `_id1`,
  `<64` → `_id2`, else `_id3`.

### 2.3 TS port implications

The sans-IO core has no clocks, so the reuse delay is owned by the async
adapter (PLAN §6.5). When the core detaches a link:
1. The adapter appends `(id, now)` to a single holding queue.
2. A **single** scheduled — and on Node, `unref()`ed — timeout processes the
   queue after ~1 second.
3. Only then is the ID returned to the core's free pools.

This preserves the race-avoidance behaviour Python relies on without keeping
the event loop alive with per-ID timers.

---

## 3. Sans-IO State Machine

### 3.1 Overview

The Python `HandlerStream` is labelled sans-IO but internally uses taskgroups
and queues. The TS core is stricter: a pure, synchronous state machine with
no promises, timers, or I/O. Async behaviour lives entirely in the
`transport/` + `async/` layers.

### 3.2 Core components

#### `RpcCore` (≈ `HandlerStream`)

Holds:
- The live sub-channel map (`id → StreamLink`), stored as `self._msgs: dict[int, StreamLink]`.
- The ID allocator (tiered pools + counter).
- (Phase 2) per-direction credit counters.

**Inputs (sync):** `core.feed(message: unknown[])` — decode header, flip sign,
route to an existing `StreamLink` or spawn a new one and invoke the registered
command handler.

**Outputs (sync):** `core.drain(): unknown[][]` — returns queued outbound
frames (pull-based). The async adapter pumps these to the transport.

**Callbacks** the core invokes on the adapter:
- `onResult(link, args, kw)` — a non-streaming reply arrived.
- `onError(link, error)` — an error reply arrived.
- `onNewCommand(link, cmdPath, args, kw)` — a new incoming command needs dispatch.
- (Phase 2) `onStreamItem`, `onStreamEnd`, `onFlowCredit`.

#### `StreamLink` (≈ `StreamLink` / `MsgLink`)

Pairs the two halves of a sub-channel. Forwards `ml_send`/`ml_recv`. Tracks
`endHere`/`endThere`/`endBoth`. Detaches from the core when both ends close
(detachment triggers the reuse-delay hold).

#### `Msg` / `MsgResult` (≈ `msg.py`)

Envelopes a single call: command path, args/kw, result storage, and (phase 2)
in/out stream-state machines and flow-control counters. `MsgResult` is the
list+dict hybrid (positional + keyword) returned to callers.

### 3.3 Stream states

From `const.py` (per direction, tracked separately for in/out):

| State   | Value | Meaning                                          |
|---------|------:|--------------------------------------------------|
| `S_END` | 3     | Terminal stream-bit-clear message sent/received  |
| `S_NEW` | 4     | No incoming message yet                          |
| `S_ON`  | 5     | We're streaming (seen/sent first message)        |
| `S_OFF` | 6     | In: we don't want streaming and signalled NO     |

Stream directions:

| Direction  | Value | Meaning          |
|------------|------:|------------------|
| `SD_NONE`  | 0     | No streaming     |
| `SD_IN`    | 1     | Incoming stream  |
| `SD_OUT`   | 2     | Outgoing stream  |
| `SD_BOTH`  | 3     | Bidirectional    |

### 3.4 State transitions (Phase 1: non-streaming)

Phase 1 only ever uses `S_NEW → S_END` (single final message each way).

**Originator side (`Msg`):**
1. `Msg.Call(cmd, a, kw, flags=0)` creates a `Msg` with `_stream_in=S_NEW`,
   `_stream_out=S_NEW`.
2. `HandlerStream.handle()` sends the initial message with flag 0 (non-streaming).
   Since `can_stream` is `False`, it calls `msg.set_end()` immediately after sending.
3. `_stream_out` goes to `S_END`.
4. When the reply arrives (flag 0), `Msg.ml_recv` calls `_set_msg(a, kw, flags)`
   and sets `_stream_in = S_END`.
5. If `_stream_out` was `S_ON`, it becomes `S_OFF`.
6. `_ended()` checks: if `_stream_in == S_END` and `_stream_out == S_END`,
   calls `self.kill()`.

**Responder side (`StreamLink` + handler):**
1. `HandlerStream.msg_in()` receives a new message. Decodes header, flips sign.
2. No existing link for this ID → creates `StreamLink`, `Msg.Call`, calls
   `self._sender.handle(rem, rem.rcmd)` in a spawned task.
3. If the incoming message has `stream=False` (flag 0), `link.set_end()` is
   called immediately (the originator's outgoing direction is done).
4. The handler runs, sends its result via `msg.result(*a, **kw)` → `ml_send` with
   flag 0 → `_stream_out` goes to `S_END`.
5. `MsgLink.set_end()` checks `end_both`: if both ends closed, calls
   `stream_detach()` on both sides → `StreamLink.stream_detach()` →
   `HandlerStream.detach(link)`.

### 3.5 State transitions (Phase 2: streaming)

**Outgoing direction (`Msg.ml_send`):**

```
S_NEW ──(first send, flag has B_STREAM)──→ S_ON
S_NEW ──(first send, flag=0 or B_ERROR)──→ S_END
S_ON  ──(send, flag=0 or B_ERROR)──────→ S_END
S_END ──(any send)──────────────────────→ (dropped, return early)
```

If `flags & B_STREAM` and `_stream_out == S_NEW` and not `B_ERROR`:
`_stream_out = S_ON`.

If not `B_STREAM` (final message): `_stream_out = S_END`.

If `_stream_out == S_END`, `ml_send` returns immediately (late messages dropped).

**Incoming direction (`Msg.ml_recv`):**

```
S_NEW ──(recv, flag has B_STREAM, no B_ERROR)──→ S_ON  (first streamed data)
S_NEW ──(recv, flag=0 or B_ERROR)─────────────→ S_END (out-of-band / final)
S_ON  ──(recv, flag=0)────────────────────────→ S_END (final, close recv_q)
S_ON  ──(recv, flag=B_ERROR)──────────────────→ (warning/flow, stay S_ON)
S_END ──(recv)────────────────────────────────→ (logged as "LATE?", dropped)
```

Detailed `ml_recv` logic:
1. If `_stream_in == S_END`: late message. Log (unless it's an `E_CANCEL`).
2. Elif not `B_STREAM`: `_set_msg(a, kw, flags)`, `_stream_in = S_END`. If
   `_stream_out == S_ON`, set `_stream_out = S_OFF`. Close `_recv_q`.
3. Elif `B_ERROR` (warning): classify as Flow or StreamError. If Flow, update
   credit counter. If StreamError and streaming, put in recv_q. Else append to
   `self.warnings`.
4. Elif `_stream_in == S_NEW`: `_set_msg(a, kw, flags)`, `_stream_in = S_ON`.
5. Elif `_recv_q is not None`: `await self._recv_q.put((a, kw))` (streamed data).
6. Else: unwanted stream. Set `_stream_in = S_OFF`, send `E_NO_STREAM` error.

After each `ml_recv`, call `_ended()` to check if both directions are `S_END`.

### 3.6 Cancellation

**Server-initiated cancel:** the responder sends `[E_CANCEL]` with `B_ERROR` as
its final message. The originator receives it, `StreamError.__new__` maps
`E_CANCEL` to `CancelledError`.

**Client-side cancel of a non-streaming call:** the originator's outgoing
direction is already `S_END` after the initial flag-0 message. `Msg.kill()` is
a no-op once `set_end()` ran. A client-side cancel merely abandons the call
locally and the eventual reply is dropped as "late". Wire-level client cancel
needs an open outgoing direction, i.e. streaming (phase 2).

**`Msg.kill()`:** Sets `_stream_in = S_END`, `_stream_out = S_END`, sets
`_msg_in` event, then calls `super().kill()` which sends `[E_CANCEL]` to the
remote via `ml_recv` (with `shield()` to prevent cancellation of the cancel).

### 3.7 `MsgLink` lifecycle

```
set_remote(remote)    → link two MsgLink instances
ml_send(a, kw, flags)  → calls remote.ml_recv(); if not B_STREAM, set_end()
set_end()              → marks this side as ended; if end_both, detach both
stream_detach()        → cleanup hook (StreamLink overrides to call HandlerStream.detach)
kill()                 → force-end + send [E_CANCEL] to remote
```

`end_here`: this side has sent its final message.
`end_there`: the remote side has sent its final message.
`end_both`: both sides ended → triggers detachment.

### 3.8 Event callbacks the core must expose

The sans-IO core communicates with the async adapter via these callbacks:

| Callback                    | When invoked                                           |
|-----------------------------|--------------------------------------------------------|
| `onNewCommand(link, path, args, kw)` | New incoming command needs dispatch          |
| `onResult(link, args, kw)`  | Non-streaming reply (flag 0) arrived                  |
| `onError(link, error)`      | Error reply (flag 2) arrived                          |
| `onWarning(link, warning)`  | Warning (flag 3) arrived (phase 2)                    |
| `onStreamItem(link, args, kw)` | Streamed data item (flag 1) arrived (phase 2)     |
| `onStreamEnd(link)`         | Stream terminated (flag 0 after streaming) (phase 2) |
| `onFlowCredit(link, credits)` | Flow control credit update (phase 2)               |
| `onDetach(link, id)`        | Link fully closed, ID can be recycled (after delay)  |

The core also needs:
- `core.feed(message: unknown[]): void` — feed a decoded CBOR array.
- `core.drain(): unknown[][]` — pull queued outbound frames.
- `core.allocateId(): number` — allocate a new originator ID.
- `core.releaseId(id: number): void` — return ID to pools (called by adapter after delay).

---

## 4. Client/Server API Surface in Python

### 4.1 Class hierarchy

```
BaseMsgHandler (abstract)
  ├── MsgHandler (dispatch: cmd_*/sub_*/stream_*)
  │     ├── BaseCmd (adds lifecycle: setup/teardown/run/task/wait_ready)
  │     │     ├── LockBaseCmd (serialized handle)
  │     │     ├── LoadCmd (dynamic app loader)
  │     │     └── BaseCmdMsg (links to a BaseMsg stream)
  │     │           ├── CmdMsg (pre-made link)
  │     │           ├── SingleCmdMsg (disconnect on error)
  │     │           │     └── ExtCmdMsg (externally-established stream)
  │     │           └── MsgStream (HandlerStream + BaseMsg stream)
  │     └── BaseSubCmd / DirCmd (config-driven sub-app tree)
  ├── MsgSender (client-side: cmd(), sub_at())
  │     └── SubMsgSender (prefix-appending sender)
  └── HandlerStream (sans-IO multiplexer: msg_in/msg_out)
        └── StreamLink (per-sub-channel forwarder)
```

### 4.2 `MsgHandler` — server-side dispatch

The central dispatch method is `MsgHandler.handle(msg, rcmd)`:

```python
async def handle(self, msg: Msg, rcmd: list[PathElem]):
    # 1. Empty path: direct cmd/stream call, else ShortCommandError
    if not rcmd:
        if not msg.can_stream and (cmd := getattr(self, "cmd", None)):
            return await msg.call_simple(cmd)
        elif (cmd := getattr(self, "stream", None)):
            return await msg.call_stream(cmd)
        else:
            raise ShortCommandError(msg.cmd)

    # 2. Documentation: "doc_" / "doc_XX"
    if len(rcmd) <= 2 and rcmd[0] == "doc_":
        doc = getattr(self, f"doc_{rcmd[1]}" if len(rcmd) > 1 else "doc", None)
        if doc is not None:
            return await msg.result(doc)

    # 3. Leaf command: "XX" → cmd_XX or stream_XX
    if len(rcmd) == 1:
        if not msg.can_stream and (cmd := getattr(self, f"cmd_{rcmd[0]}", None)):
            return await msg.call_simple(cmd)
        if (cmd := getattr(self, f"stream_{rcmd[0]}", None)):
            return await msg.call_stream(cmd)

    # 4. Readiness check: "rdy_"
    is_rdy = False
    if rcmd[0] == "rdy_":
        if L and not self.SKIP_RDY and hasattr(self, "wait_ready"):
            if await self.wait_ready(wait=True):
                raise NotReadyError(msg.cmd, rcmd)
        is_rdy = True

    # 5. Subcommand recursion: pop last element, find sub_XX
    scmd = rcmd.pop()
    if (sub := self.find_sub(scmd)) is not None:
        return await sub.handle(msg, rcmd)

    # 6. Rdy fallback: result(None)
    if is_rdy:
        return await msg.result(None)

    # 7. Unknown: KeyError (marshalled as _rErr)
    raise KeyError(scmd, ...)
```

**Dispatch order (critical for TS port to match):**
1. Empty path → direct `cmd`/`stream` method, else `ShortCommandError`
2. `doc_` / `doc_XX` → return doc dict
3. Single-element leaf → `cmd_XX` (non-streaming) or `stream_XX` (streaming)
4. `rdy_` prefix → readiness check (L-gated)
5. Sub-command → `find_sub(scmd)` → recurse
6. `rdy_` fallback → `result(None)`
7. `KeyError` (marshalled as exception, not `E_NO_CMD`)

`find_sub` checks `_subs` registry (Dispatcher mixin) first, then falls back to
`getattr(self, "sub_" + scmd, None)`.

### 4.3 `MsgSender` — client-side API

```python
class MsgSender(BaseMsgHandler):
    def __init__(self, root: MsgRoot):
        self._root = root

    def cmd(self, cmd: Path, *a, **kw) -> Caller:
        """Issue a command. Returns a Caller (awaitable or async context manager)."""
        return Caller(self, (cmd, a, kw))

    def sub_at(self, prefix: Path, caller=None, cmd=False) -> MsgSender | Callable:
        """Resolve a prefix. Returns a SubMsgSender or a callable."""
        ...

    def __getattr__(self, x: str) -> MsgSender:
        """Shortcut: sender.foo → sender.sub_at(P("foo"))"""
        return self.sub_at(Path.build((x,)))
```

### 4.4 `Caller` — the awaitable/context-manager

```python
class Caller:
    def __init__(self, sender, data: tuple[cmd, args, kw], _list=NotGiven):
        ...

    def __await__(self):
        """Direct RPC call: `res = await sender.cmd("foo", 42)`"""
        return self._call().__await__()

    async def _call(self):
        msg = Msg.Call(cmd, args, kw)
        await self.sender.handle(msg, msg.rcmd)
        await msg.wait_replied()
        # Unpack result based on _list mode
        ...

    async def __aenter__(self) -> Msg:
        """Streaming: `async with sender.cmd("bar") as m: ...`"""
        ...

    def stream(self, size=42) -> Self:
        """Mark as bidirectional streaming."""
        self._dir = SD_BOTH
        return self

    def stream_in(self, size=42) -> Self:
        """Mark as incoming-only streaming."""
        self._dir = SD_IN
        return self

    def stream_out(self) -> Self:
        """Mark as outgoing-only streaming."""
        self._dir = SD_OUT
        return self
```

**Result unpacking modes (`_list` parameter):**
- `NotGiven` (default): return the `Msg` object.
- `True`: always return a list (`msg.args`). Raises if `msg.kw` is non-empty.
- `False`: always return a dict (`msg.kw`). Raises if `msg.args` is non-empty.
- `None` (best effort): single arg → return it directly; only kw → return kw;
  both → return `Msg` object; multiple args → return all as list.

### 4.5 `MsgResult` — the list+dict hybrid

Returned to callers. Simultaneously a list (positional args) and dict (keywords):

```python
class MsgResult(Iterable):
    _a: Sequence    # positional args (read-only)
    _kw: dict       # keyword args

    @property
    def args(self) -> Sequence: ...     # positional args
    @property
    def kw(self) -> MutableMapping: ...  # keyword args

    def __getitem__(self, k): ...        # int → args[k], str → kw[k]
    def __len__(self): ...               # len(positional)
    def __iter__(self): ...              # iterate positional
    def get(self, k, default=None): ...  # safe access
    def keys(self): ...                  # kw keys
    def values(self): ...                # kw values
    def items(self): ...                 # kw items
```

### 4.6 `HandlerStream` — the sans-IO multiplexer

```python
class HandlerStream(MsgHandler):
    def __init__(self, sender: BaseMsgHandler | None, logger=None):
        self._msgs: dict[int, StreamLink] = {}
        self._send_q = Queue(9)     # outbound frame queue
        self._recv_q = Queue(99)    # inbound dispatch queue
        self._sender = sender
        self.closing = True
        # ID pools
        self._id1: set[int] = set()  # <6
        if L:
            self._id2: set[int] = set()  # <64
        self._id3: set[int] = set()  # rest
        self._id = 0

    async def msg_in(self, msg: list) -> None:
        """Feed a decoded CBOR array (incoming from wire)."""

    async def msg_out(self) -> list:
        """Pull the next outbound CBOR array (to write to wire)."""

    async def send(self, link, a, kw, flag) -> None:
        """Queue an outbound message."""

    async def handle(self, msg, rcmd) -> None:
        """Forward a new outgoing command to the remote side."""

    def attach(self, link) -> None:
        """Register a link in _msgs."""

    def detach(self, link) -> None:
        """Remove a link, recycle its ID (with delay in L build)."""
```

### 4.7 `StreamLink` — per-sub-channel forwarder

```python
class StreamLink(MsgLink):
    def __init__(self, stream: HandlerStream, id: int):
        self.__stream = stream
        self.id = id
        self.task = None

    async def ml_recv(self, a, kw, flags):
        """Data to be forwarded across the link (to wire)."""
        await self.__stream.send(self, a, kw, flags)

    async def ml_send(self, a, kw, flags):
        """Data to be forwarded to our remote (from wire)."""
        await super().ml_send(a, kw, flags)

    def stream_detach(self):
        """Called when both ends closed. Detach from HandlerStream."""
        self.__stream.detach(self)
        self.__stream = None
```

### 4.8 Connection / transport layer

**`BaseConnIter`** — abstract listener:

```python
class BaseConnIter:
    async def accept(self) -> Never:
        """Override: accept connections, call self.add_conn(conn)."""
    def add_conn(self, c) -> Awaitable:
        return self.q.put(c)
    async def __aiter__(self):
        """Yields incoming BaseConn objects."""
```

Concrete implementations: `TcpIter`, `UnixIter`, `WsIter`.

**`AioStream`** (in `anyio.py`) — bridges `HandlerStream` to an anyio stream:

```python
class AioStream(HandlerStream):
    def __init__(self, cmd, stream, codec=None, **kw):
        ...
    async def read_stream(self):
        """Read from stream, feed to msg_in."""
        while True:
            buf = await conn.read(4096)
            codec.feed(buf)
            for msg in codec:
                await self.msg_in(msg)
    async def write_stream(self):
        """Pull from msg_out, write to stream."""
        while True:
            msg = await self.msg_out()
            buf = codec.encode(msg)
            await conn.write(buf)
```

**`rpc_on_aiostream`** — convenience context manager:

```python
@asynccontextmanager
async def rpc_on_aiostream(cmd, stream, *, codec=None, debug=False):
    """Run a command handler on top of an anyio stream."""
    async with stream, AioStream(cmd, stream, ...) as hs:
        yield hs
```

### 4.9 `BaseCmdMsg` / `CmdMsg` / `ExtCmdMsg` — full-stack connection handlers

These tie the command tree to a `BaseMsg` stream:

- **`BaseCmdMsg`**: abstract; overrides `stream()` to create the transport.
  Handles auth redirection, local command interception, and remote forwarding.
- **`CmdMsg`**: has a pre-made `link` (passed to constructor).
- **`SingleCmdMsg`**: disconnects on error without propagating.
- **`ExtCmdMsg`**: wraps an externally-established stream (used by listeners).

**`BaseCmdMsg.handle()`** intercepts:
1. Local commands (`cmd_XX`/`stream_XX` on this handler) — handled locally.
2. `dir_` requests — merged with remote directory.
3. Everything else — forwarded to the remote via `self.__stream.handle()`.

### 4.10 Listener pattern (`BaseListenOneCmd` / `BaseListenCmd`)

```python
class BaseListenOneCmd(BaseLayerCmd):
    def listener(self) -> BaseConnIter:
        """Override: return a connection iterator."""
    def wrapper(self, conn) -> BaseMsg:
        """Wrap connection in a stream stack (default: serial_stack)."""
    async def handler(self, conn):
        """Create ExtCmdMsg, attach, run, wait for stop."""
    async def task(self):
        """Accept loop: async for conn in conns: tg.start_soon(handler, conn)."""
```

`BaseListenCmd` is the multi-connection variant: each connection gets a
numbered sub-app slot.

### 4.11 TS API surface to mirror

Based on the Python API, the TS port should expose:

```ts
// Server
class RpcServer {
  constructor(opts: { codec?: Codec });
  register(name: string, handler: (msg: Msg) => Promise<void>): void;
  listen(opts: TransportOpts): Promise<void>;
}

// Client
class Rpc {
  static connect(url: string): Promise<Rpc>;
  cmd(path: Path | string, ...args: unknown[]): Caller;
  sub_at(prefix: Path): RpcSender;
}

// Caller (awaitable or async iterable)
class Caller implements PromiseLike<MsgResult>, AsyncIterable<MsgResult> {
  // await caller → MsgResult (non-streaming)
  // for await (const m of caller) → streamed items (phase 2)
  stream(size?: number): this;
  stream_in(size?: number): this;
  stream_out(): this;
}

// MsgResult (list + dict hybrid)
class MsgResult {
  readonly args: readonly unknown[];
  readonly kw: ReadonlyMap<string, unknown>;
  get(key: number | string): unknown;
  [Symbol.iterator](): Iterator<unknown>;
}

// Msg (envelope)
class Msg {
  readonly cmd: Path;
  readonly args: readonly unknown[];
  readonly kw: Map<string, unknown>;
  async result(...args: unknown[]): Promise<void>;
  async error(err: Error): Promise<void>;
  get can_stream(): boolean;
}
```

---

## 5. Summary of key implementation decisions for the TS port

1. **Header packing:** use `(id << 2) | (flag & 3)` and `w >> 2`,
   mirroring Python's bitwise shifts exactly. IDs are recycled so
   in-flight counts stay small — JS 32-bit overflow (> 2²⁹) is unreachable.

2. **Sign flip:** originator uses positive IDs (≥ 1); responder flips to
   negative; replies use the negative ID. ID `0` is never live.

3. **Command slot:** plain CBOR array, NOT tag 39. Tag 39 is only for `Path`
   *values* in args/kwargs.

4. **kwargs:** use `Map` for all CBOR maps; `push_kw`/`pop_kw` logic determines
   when to append the trailing map.

5. **ID pools:** three tiers (`<6`, `<64`, rest); allocate from smallest first.
   Recycle with ~1 s delay in the async adapter (single unref'ed timer).

6. **Sans-IO core:** pure synchronous state machine. No promises, timers, or
   I/O. Communication via `feed()`/`drain()` and callbacks.

7. **Dispatch order:** empty path → `doc_` → leaf `cmd_`/`stream_` → `rdy_` →
   `sub_` recursion → `rdy_` fallback → `KeyError`.

8. **Error marshalling:** `KeyError` (unknown command) → tag 27 `["_rErr",
   "KeyError", …]`, NOT `E_NO_CMD`. `E_NO_CMD` only when no handler at all.

9. **Cancellation:** server sends `[E_CANCEL]` with `B_ERROR`. Client-side
   cancel of non-streaming call is local-only (outgoing direction already
   closed).

10. **`B_WARNING_INTERNAL` reconstruction:** flag 3 + single integer payload →
    flag 7 (flow control). User warnings with a lone integer must append `{}`.
