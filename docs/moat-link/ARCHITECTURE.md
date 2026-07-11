# Architecture — moat.link

MoaT-Link enhances MQTT messaging with structured data types and defined
metadata (origin + timestamp), supporting a minimal unified pub/sub
messaging service. Default backend is MQTT with `std-cbor` codec
(`link/_cfg.yaml`, `link/__init__.py`).

## Client (`link/client.py`)

- **`LinkCommon`** (base `CmdCommon`): shared base for `Link` and
  `BasicLink`. Holds client ID, name, command queue, `MsgSender`, the `Hello`
  handshake; `_connect_one` establishes TCP/Unix + auth handshake.
- **`Link`** (extends `LinkCommon`+`CtxObj`): full client = MQTT backend **plus**
  a server RPC connection. `_ctx` opens the backend via `get_backend`, starts
  ping/id tasks, runs `_run_server_link` to discover/connect to a server.
  Process-wide singleton via `_the_link` `ContextVar`.
- **`BasicLink`**: simpler direct MQTT-only link, no server (raw backend
  access).
- **`LinkSender`** (extends `MsgSender`): client front-end exposing `d`/`d_`/
  `e`/`i`/`cl` namespaces — `d_get/d_set/d_search/d_walk/d_watch`,
  `send`/`monitor`, `code_at`, `get_codec_tree`.
- **`Watcher`** (`CtxObj`): coalesces MQTT subscription + server `d.walk`
  into one async iterator / node tree. `_current` pulls the snapshot;
  `_updates` streams live MQTT; `get_node` returns a populated `Node`.
  `Walker`: trimmed subtree retriever (no updates).

## Data model (`link/node/__init__.py`)

- **`Node`** (attrs): one MoaT-Link item holding `_data`, `_meta`, `_sub`
  children. `set` applies timestamp-based conflict resolution; `get`/
  `add_child` build subtrees; `dump`/`load` serialize with path shortening;
  `walk`/`finder`/`search`/`collect` support wildcard (`+`/`#`/range)
  matching. **`NodeFinder`** walks wildcard paths returning matches in
  precedence order.
- **`CodecNode`** (`node/codec.py`, extends `Node`): carries
  `enc_value`/`dec_value` procs compiled from `encode`/`decode` snippets —
  the runtime codec-conversion tree used by gates.

## Metadata (`link/meta.py`)

**`MsgMeta`** (attrs, proxied as `_MM`): slots `origin` (0), `timestamp` (1),
plus arbitrary `kw`. `encode`/`decode` pack/unpack to a `/`-`\` delimited
string carried in the MQTT5 `MoaT` user-property; non-string items are
CBOR+b85-encoded. `restore` reconstructs from arrays.

## Backend (`link/backend/__init__.py`, `backend/mqtt.py`)

- **`Backend`** (ABC): abstract `connect`/`monitor`/`send`/`send_error`;
  `get_backend` imports the `cfg.backend.driver` module. `Message`/
  `RawMessage` are incoming containers.
- **MQTT `Backend`**: wraps `moat.lib.mqtt.AsyncMQTTClient`. `monitor`
  subscribes (optional `#`) yielding a `_SubGet` iterator; `send` encodes via
  the configured codec, attaches `MsgMeta.encode()` to the `MoaT` user
  property, validates UTF-8 for str payloads, publishes. `_SubGet` decodes
  incoming, reconstructs `MsgMeta`, falls back to `RawMessage` on decode
  failure, reports errors to `:R.error.link.mqtt.*`.

## Server (`link/server/_server.py`)

- **`Server`** (extends `MsgHandler`): owns authoritative `data` (persistent
  `Node`) and `rdata` (transient `run.*`). `_backend_monitor` consumes `:R/#`
  → `maybe_update` → `Node.set` (timestamp-gated) + `write_monitor` broadcast;
  `_backend_sender` republishes locally-originated changes. Uses `asyncactor`
  for leader election (`_pinger`).
- **`ServerClient`** (extends `LinkCommon`): per-client handler; `setup`
  delegates `d`→`_Sub_d`, `e`→`_Sub_e`, `s`→`_Sub_s`, `i`→`_Sub_i`.
  - `_Sub_d`: `d_get_stream_/d_set_/d_delete_/d_walk_stream_/d_search_/
    d_deltree_stream_`.
  - `_Sub_e`: error reporting (`exc/info/ack/ok/mon`). `_Sub_i`: server info
    (`state/error/stamp/sync/checkid`). `_Sub_s`: state save/load to disk.

## Gateways (`link/gate/`)

Bidirectional bridges between a MoaT-Link subtree and an external system,
with timestamp-based conflict resolution.

- **`Gate`** (abstract): described by a dict at `:R.gate.NAME` with
  `src`/`dst`/`driver`/`codec`/`retain`. Algorithm: if data missing on one
  side or arrives from the other, copy across; if equal, no-op; if source meta
  says it came from the destination, copy dest→src; else copy src→dest.
  Subclasses override `get_dst`/`set_dst`/`newer_dst`/`is_update`/`run_`.
- **`GateNode`** (extends `Node`): tracks internal (`data_`/`meta`) and
  external (`ext_data`/`ext_meta`) values + `lock` + `todo` flag.
  `Gate.run` builds a fresh `GateNode` tree, starts `get_src` (watches Link
  via `d_watch`) and `get_dst` (driver), waits for both initial scans, then
  `run_` reconciles pending `todo` nodes and pushes via `_set_dst`/`_set_src`.
- **`DelayedGate`**: adds a `delay` (default 0.1 s) using a `TimerMap`; a
  matching update from the opposite direction cancels the pending one —
  network-split recovery.
- **Drivers**: `gate/mqtt.py` (raw MQTT, codec-vector trees, optional
  secondary broker), `gate/kv.py` (legacy MoaT-KV bridge), `gate/link.py`
  (Link↔Link sync, extends `DelayedGate`), `gate/venus.py` (Victron Venus OS
  JSON, forces `codec='json'`, `N/`/`W/`/`R/` topics).
- **`run_gate`**: dispatcher — reads config at `:R.gate.<name>`, imports
  `moat.link.gate.<driver>`, instantiates its `Gate`, calls `.run()`. Invoked
  by `gate run` CLI.

Each gate's `codec` (default `"cbor"`) is for the **destination** side; the
source (MoaT-Link) side is always `std-cbor`.

## Code exec (`link/code/run.py`)

**`Code`** compiles/runs Python snippets stored under `code.exec`;
`_ReturnRewriter` rewrites module-level `return` into `raise ReturnValue`.
Handles async/sync/thread-offload. Reached via `LinkSender.code_at` →
`CodeCaller`.

## Control flow

**Publish** (client→server→MQTT): `LinkSender.d_set` → either `backend.send`
(encode, attach `MsgMeta` to `MoaT` user-property, publish to `:R.<path>`) or
server RPC `d.set` → `Node.set` (timestamp-gated) → `_backend_sender`
republishes.

**Subscribe** (MQTT→server→client): `Server._backend_monitor` consumes `:R/#`
→ `maybe_update` → `Node.set` + `write_monitor` broadcast; clients read via
`d.walk`/`d.get` RPC and/or direct MQTT `monitor`; `Watcher` merges both.

**RPC**: clients talk to the server over a framed RPC stream (`moat.lib.rpc`,
codec `std-cbor`) via `TCPConn`/`UnixConn` (`link/conn.py`). Commands
namespaced `d.*`/`e.*`/`i.*`/`s.*`/`cl/<id>`/`srv/<id>`.

**Liveness**: `Link._send_ping` publishes `run.ping.id.<id>` + `run.id.<id>`;
server actor `_pinger` coordinates leadership via `asyncactor` on
`run.service.main.ping`.

## Entry points

- Programmatic: `Link(cfg, name=None, common=False, only=None)` (async ctx →
  `LinkSender`); `BasicLink(cfg, name, data)`.
- Publishing: `await sdr.d_set(Path("my.topic"), data, meta=MsgMeta(origin="me"))`.
- Subscribing: `sdr.d_watch(path, …)` (async iter), `sdr.d_walk(path)`,
  `sdr.as_dict(path)`.
- CLI: `link/_main.py`, `link/cmd/`, `gate/_main.py` (`run`/`set`/`list`/
  `delete`), `code/_main.py` (`get`/`set`/`list`/`delete`/`edit`),
  `server/_main.py` (launcher).
- Server: `Server(cfg, name, …)` under `link/server/_main.py`.
