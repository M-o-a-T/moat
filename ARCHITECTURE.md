# Architecture

High-level architecture of the MoaT monorepo. This file is an **index**:
each subsystem has its own detailed `ARCHITECTURE.md` under
`docs/moat-XX/ARCHITECTURE.md` (linked below). Keep entries here to a single
"what does this subsystem do" paragraph; put depth in the per-subsystem
files. Update when you discover structural facts.

## Overview

MoaT ("Master of all Things") is an async-Python framework for home/solar
energy management and IoT control. Three pillars (see `README.md`):

- **MoaT-Link** (`moat/link/`) — structured pub/sub messaging over MQTT with
  typed metadata, the modern data backbone.
- **MicroPython integration** (`moat/micro/`) — satellite MCUs running
  patched-MicroPython, reached seamlessly over a reliable RPC link.
- **Domain applications** (`moat/ems/`, `moat/dev/`, `moat/cad/`, …).

Everything runs on **anyio** (never `asyncio` directly) using **structured
concurrency**; `trio` is the default backend (`moat/main.py:cmd`). Monorepo;
all code lives under `moat/`. Each `moat.X.Y` package owns `moat/X/Y/`,
`docs/moat-X-Y`, `packaging/moat-X-Y`, `tests/moat_X_Y`,
`examples/moat-X-Y`, and a `_cfg.yaml` declaring config defaults.

## Subsystem index

> `moat.lib` is a **collection** of shared support libraries (not one
> subsystem), so it is split across `moat-lib-*` files.

### Foundation — `moat.lib` (collection) + `moat.util`

- **[`moat-lib-micro`](docs/moat-lib-micro/ARCHITECTURE.md)** — the
  CPython/MicroPython compatibility shim: re-exports anyio under neutral
  names, augments `TaskGroup` with `spawn()`, owns the `ACM`/`AC_use`
  lifecycle pattern. *(There is no `moat.lib.compat`; this is it.)*
- **[`moat-lib-config`](docs/moat-lib-config/ARCHITECTURE.md)** —
  hierarchical YAML config: layered loading, `$base` inheritance, deferred
  per-package `_cfg.yaml` registration, live-update monitoring.
- **[`moat-lib-run`](docs/moat-lib-run/ARCHITECTURE.md)** — CLI orchestration:
  the top-level async Click command, runtime setup, and dynamic subcommand
  discovery (`Loader`/`_main.cli` convention).
- **[`moat-lib-path`](docs/moat-lib-path/ARCHITECTURE.md)** — `Path`/
  `PathElem`: hierarchical typed addressing with shortening/lengthening; the
  universal identifier.
- **[`moat-lib-codec`](docs/moat-lib-codec/ARCHITECTURE.md)** — pluggable
  (de)serialization: `Codec` ABC + `Extension` registry; CBOR/std-cbor/
  msgpack/json/yaml/etc.
- **[`moat-lib-stream`](docs/moat-lib-stream/ARCHITECTURE.md)** — layered
  async transport: `BaseBuf→BaseBlk→BaseMsg` with TCP/Unix/WS/serial
  connectors, reliability/retransmission, console muxing.
- **[`moat-lib-rpc`](docs/moat-lib-rpc/ARCHITECTURE.md)** — request/response
  + streaming RPC: `MsgHandler`/`MsgSender`, `Msg`/`Caller` (dual-awaitable),
  command trees (`RootCmd`/`DirCmd`).
- **[`moat-lib-proxy`](docs/moat-lib-proxy/ARCHITECTURE.md)** — `Proxy`/
  `as_proxy`: type-tag objects so they survive codec transport by registered
  name.
- **[`moat-lib-mqtt`](docs/moat-lib-mqtt/ARCHITECTURE.md)** — the **active**
  MQTT stack (vendored mqttproto, MQTT-5); what `moat.link` uses.
- **[`moat-lib-broadcast`](docs/moat-lib-broadcast/ARCHITECTURE.md)** —
  pub/sub fan-out (`Broadcaster`/`BroadcastReader`) with `LostData` overflow
  signaling.
- **[`moat-lib-pid`](docs/moat-lib-pid/ARCHITECTURE.md)** — advanced PID
  controllers with derivative filtering, anti-windup, state save/restore.
- **[`moat-lib-gpio`](docs/moat-lib-gpio/ARCHITECTURE.md)** — Linux GPIO
  character-device abstraction (`Chip`/`Line`/`open_chip`).
- **[`moat-lib-ring`](docs/moat-lib-ring/ARCHITECTURE.md)** — fixed-size
  overwrite byte ring buffer (rolling tail for logs/serial capture).
- **[`moat-lib-diffiehellman`](docs/moat-lib-diffiehellman/ARCHITECTURE.md)**
  — Diffie-Hellman key exchange for RPC auth.
- **[`moat-lib-repl`](docs/moat-lib-repl/ARCHITECTURE.md)** — interactive
  async REPL: line editor, history, completion, terminfo, pager.
- **[`moat-lib-priomap`](docs/moat-lib-priomap/ARCHITECTURE.md)** —
  priority-ordered map for ranked dispatch.
- **[`moat-util`](docs/moat-util/ARCHITECTURE.md)** — cross-cutting utils:
  `attrdict`, `NotGiven`, `CtxObj`, `ValueEvent`, `Queue`, YAML, merge
  (lazy facade).

### Core

- **[`moat-link`](docs/moat-link/ARCHITECTURE.md)** — enhances MQTT with
  typed data + metadata (origin + timestamp); clients, server, gateways,
  metadata packing, and code-exec. The modern data backbone.
- **[`moat-micro`](docs/moat-micro/ARCHITECTURE.md)** — MicroPython device
  integration: a reliable CBOR RPC over one serial/TCP wire, with embedded
  boot-state machine, apps/parts, and host CLI for setup/runtime.

### Legacy & adjacent stores

- **[`moat-kv`](docs/moat-kv/ARCHITECTURE.md)** — **deprecated** distributed
  replicated KV with tamper-evident change-chains; reachable from Link only
  via `gate/kv.py`.
- **[`moat-db`](docs/moat-db/ARCHITECTURE.md)** — relational layer
  (SQLAlchemy 2.0 + Alembic) for structured/tabular app data; unrelated to
  KV.

### Industrial comms & transports

- **[`moat-modbus`](docs/moat-modbus/ARCHITECTURE.md)** — opinionated async
  Modbus-TCP/RTU client+server; bridges register values to MoaT-Link.
- **[`moat-mqtt`](docs/moat-mqtt/ARCHITECTURE.md)** — **deprecated** hbmqtt
  fork (MQTT 3.1.1 stack + broker); superseded by `moat.lib.mqtt`.
- **[`moat-bus`](docs/moat-bus/ARCHITECTURE.md)** — sans-IO multi-wire
  hardware bus protocol (collision detection, CRC, priority arbitration).

### Domain applications

- **[`moat-ems`](docs/moat-ems/ARCHITECTURE.md)** — energy management: BMS
  batteries, Victron D-Bus inverter control, OR-Tools LP scheduler.
- **[`moat-cad`](docs/moat-cad/ARCHITECTURE.md)** — parametric 3D CAD helpers
  (build123d/CadQuery); CQ-editor/G-code CLI. Shallow MoaT ties.
- **[`moat-signal`](docs/moat-signal/ARCHITECTURE.md)** — standalone async
  Signal-messenger client over signal-cli JSON-RPC; no `moat.*` imports.
- **[`moat-dev`](docs/moat-dev/ARCHITECTURE.md)** — CLI device controllers:
  heaters (`heat/`), motors (`sew/`); uses Modbus + MQTT/KV/Link.

### Integration surfaces

- **[`moat-mcp`](docs/moat-mcp/ARCHITECTURE.md)** — MCP server over stdio
  exposing MoaT-Link tools to AI clients.
- **[`moat-src`](docs/moat-src/ARCHITECTURE.md)** — monorepo/source-tree
  management: scaffolding, tagging, forge migration.
- **[`moat-nodered`](docs/moat-nodered/ARCHITECTURE.md)** — Node-RED plugin
  encoding MoaT metadata to MQTT user-properties (JS counterpart to
  `link/meta.py`).
- **[`moat-api`](docs/moat-api/ARCHITECTURE.md)** — CFFI wrappers for vendor
  C libs (e.g. Bosch BMV080 sensor).
- **[`moat-pdb`](docs/moat-pdb/ARCHITECTURE.md)** — trivial `breakpoint()`
  shim.

## Cross-cutting themes

These recur across subsystems; see the linked files for depth.

- **anyio over asyncio** — portable across trio/asyncio; trio default. Never
  `import asyncio` (AGENTS.md).
- **`ACM`/`AC_use` over raw `async with`** — deterministic per-object
  resource lifecycle with cross-task ownership checks (`moat-lib-micro`).
- **Dynamic subcommand discovery** — `_main.cli` convention + `Loader` lets
  each package self-register its CLI and config (`moat-lib-run`).
- **Per-package `_cfg.yaml` + `register()`** — modular config defaults merged
  hierarchically (`moat-lib-config`).
- **`moat.lib.micro` as the compat bridge** — one async API for CPython and
  patched-MicroPython; shared RPC code on host and device (`moat-micro`).
- **MoaT-Link over MoaT-KV** — Link is a lighter pub/sub layer replacing KV's
  heavier replicated-chain model; `gate/kv` is the migration bridge.
- **Sans-IO protocol cores** (`moat-bus`, `moat-modbus` framers) — testable,
  transport-independent state machines.
- **Proxy-by-name** — objects cross codec/transports via `as_proxy`
  registration rather than ad-hoc serialization (`moat-lib-proxy`).

## Entry points (summary)

Detailed per-mode entry points live in each subsystem file. Highlights:

- **CLI**: `moat` console script → `moat/main.py:cmd` (or `./mt` /
  `python -m moat`). Subcommands discovered via `moat.<pkg>._main.cli`.
- **Link client/server**: `Link(cfg)` / `BasicLink(cfg)` (`link/client.py`);
  `Server(cfg,name)` via `link/server/_main.py`.
- **Gateway**: `run_gate(name)` (`link/gate/__init__.py`) via `moat link gate
  run`.
- **MicroPython device**: `micro/_embed/main.py` → `moat.go()` → `go_.py` →
  `micro/main.py:main`.
- **Micro host**: `moat micro {run,setup,install,<cmd>}`.
- **MCP**: `moat mcp stdio` → `mcp/_server.py:run`.
- **Tests**: `pytest` (`tests/`); `moat.src.test` provides `run`/`raises`
  wrappers. Type checking via `ty` (`tool.ty.src.include` in `pyproject.toml`).

External dependencies are listed in `pyproject.toml` (anyio/trio/asyncclick/
pydantic/pymodbus/sqlalchemy/mcp/httpx/asyncdbus/asyncactor/stamina, etc.).
