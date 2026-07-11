# Architecture — moat.kv (deprecated)

**Deprecated distributed replicated key-value store** (`kv/client.py:6`:
*"MoaT-KV is deprecated. Use MoaT-Link instead."*). Reached from modern code
only via the `moat.link.gate.kv` bridge — see `moat-link/ARCHITECTURE.md`.

## Data model

A server holds a tree of typed entries; each value carries a tamper-evident
**change-chain** (`NodeEvent`/`chain`) recording which server-node wrote it at
which `tick`. Clients connect over TCP/MQTT and mirror/watch subtrees.

- **`RootEntry`** + parallel **`MetaRootEntry`** (`kv/types.py`) — root + the
  `None`-keyed meta subtree containing typed sub-hierarchies: `type`,
  `match`, `acl`, `codec`, `conv`, `actor` (`MetaRootEntry.SUBTYPES`).
- **`Entry`** (`model.py:632`) — one key/value node: `_data`, `chain`, `tock`,
  `_sub` children, `monitors`. Polymorphic dispatch via `SUBTYPE`/`SUBTYPES`.
- **`Node`** (`model.py:38`) — a participating server replica; tracks per-tick
  presence/deletion/supersession via `RangeSet`s. `NodeSet` (`:307`),
  `NodeEvent` (`:363`), `UpdateEvent` (`:561`, serializable with codec hooks).
  **`Watcher`** (`:1039`) — async-ctx + async-iter pushing `UpdateEvent`s
  into a bounded queue.

## Typed meta-tree (`kv/types.py`)

- `TypeRoot`/`TypeEntry` — JSON-schema + custom-proc value validation.
- `MatchRoot`/`MatchEntry` + `NodeFinder` — wildcard-path (`+`/`#`) routing of
  paths to types.
- `CodecRoot`/`CodecEntry`, `ConvRoot`/`ConvName`/`ConvEntry`/`ConvNull` —
  encode/decode pipelines.
- `AclRoot`/`AclName`/`AclEntry`, `ACLFinder`/`ACLStepper`/`NullACL` —
  permission checking along paths.

## Client mirrors (`kv/obj/__init__.py`, `obj/command.py`)

`ClientEntry`/`ClientRoot` — client-side cached mirror of a server subtree;
subclasses override `child_type()`/`set_value()`. `NamedRoot` adds name
caching. Used by `config.py` (`ConfigRoot`/`ConfigEntry`), `code.py`
(`CodeRoot`/`ModuleRoot`), `errors.py` (`ErrorRoot`), `runner.py`
(`RunnerRoot`).

## Client (`kv/client.py`)

`Client` — the connection. `open_client(...)` (async ctx mgr) and
`client_scope(...)` (asyncscope service) are the public entry points
(`__all__`). Provides `get/set/delete/get_tree/watch/mirror` RPCs over a
framed protocol with request/reply streaming (`StreamedRequest`;
`NoData`/`ManyData` sentinel errors). CLI in `kv/_main.py` (`cli` group via
`load_subgroup`); leaf commands in `kv/command/*.py`.

## Server (`kv/server.py`)

- **`Server`** (`:1360`) — owns the authoritative `RootEntry`, listens on
  configured `bind` sockets, runs `asyncactor`-based cluster sync
  (`TagEvent`/`UntagEvent`/`GoodNodeEvent`), dispatches per-connection
  `ServerClient` (`:662`) / `StreamCommand` (`:117`) handlers.
- Supervisor: the "runner" (`kv/runner.py`: `RunnerEntry`/`RunnerNode`/
  `RunnerMsg`) executes uploaded code. Uploadable-code store `kv/code.py`
  (`CodeRoot`/`ModuleRoot`); error store `kv/errors.py`.

## Backend (`kv/backend/`)

`Backend` ABC (`__init__.py`): abstract `connect()`/`monitor()`/`send()` +
`spawn()`/`aclose()`. `get_backend(name)` dynamically imports. Sole
implementation: **`MqttBackend`** (`mqtt.py`) wrapping `moat.mqtt.client.
MQTTClient` (the deprecated hbmqtt fork).

## Bridge to MoaT-Link (`link/gate/kv.py`)

Subclasses the generic `Gate`. `run_()` opens a real KV client
(`open_client("moat.link.gate.kv", **cfg["kv"])`). `get_dst()` watches the KV
tree, reconstructs full paths via `PathLongener`, pushes changes into Link as
`set_src(path, value, MsgMeta(origin=chain.node, t=chain.tick))` —
translating KV's `chain` into Link's `MsgMeta`. `set_dst()` writes
Link-originated changes back into KV. `is_update()` suppresses echo loops;
`newer_dst()` resolves concurrent-edit precedence. So KV is consumed purely
as one possible `dst` transport behind Link's `Gate` abstraction.
