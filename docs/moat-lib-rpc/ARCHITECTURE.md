# Architecture — moat.lib.rpc

MoaT's command multiplexer / RPC core: request/response + streaming RPC over
a message stream, with hierarchical command trees. The same protocol runs on
both the CPython host and the MicroPython device.

## Files

- `base.py` — `BaseMsgHandler`/`MsgHandler`/`MsgSender`, `Caller`.
- `msg.py` — `Msg`/`MsgLink`/`MsgResult` message envelopes.
- `cmd/` — command trees: `RootCmd`, `DirCmd`, `BaseLayerCmd`,
  `BaseListenCmd`, layered/listening command bases, `cmd/_base.py`.
- `conn/` — connection iterators tying a handler to a stream (`tcp.py`, …).
- `stream/` — streaming-RPC helpers.
- `auth/` — authentication over RPC.
- `alert.py`, `nest.py` — alert propagation; nesting (`rpc_on_rpc`).

## Core types

- **`BaseMsgHandler` / `MsgHandler` / `MsgSender`** (`base.py`) — the message
  exchange engine. `MsgSender` is the outbound side; `MsgHandler` dispatches
  inbound messages to registered commands.
- **`Msg` / `MsgLink` / `MsgResult`** (`msg.py`) — message envelopes linking a
  request to its reply/stream and carrying the result.
- **`Caller`** (`base.py`) — dual-awaitable: implements both `__await__`
  (CPython) and `__iter__` (MicroPython, relying on µPy native coroutine
  iteration). This is the cross-runtime awaitable bridge.
- **Command trees** (`cmd/`): `RootCmd` (root of the tree), `DirCmd`
  (directory/sub-tree node), `BaseLayerCmd`, `BaseListenCmd`. Apps subclass
  `BaseCmd` and register `cmd_*` methods; `sub_at(path)` descends into a
  subtree. `add_app_prefix("moat.micro.app")` registers app namespaces
  (see `moat/micro/__init__.py`).

## Command dispatch

Commands are addressed by `moat.lib.path.Path`. A `RootCmd` holds the top
level; `DirCmd`/layered cmds map path segments to child handlers. `MsgSender`
issues a `Msg`; the peer `MsgHandler` resolves the path to a `cmd_*` method,
awaits it, and returns a `MsgResult` (single value) or streams via `MsgLink`.

## Streaming

Beyond request/response, RPC supports streaming results and bidirectional
streams (`stream/`): a single `Msg` can open a linked channel over which
multiple values flow in either direction until closed. Used by MoaT-Link
`d.walk`/`d.watch` and by MicroPython file transfers.

### Shared iterators

`BaseCmdMsg` provides a `mon_` streaming command that multiplexes remote
iterators locally.  Multiple local consumers can subscribe to the same
remote streaming command via `mon_`; the first subscriber opens the remote
stream and subsequent subscribers receive the same data through
`moat.lib.broadcast.Broadcaster` readers.  When the last subscriber
disconnects, the remote stream is closed.
This avoids opening multiple remote streams for the same data source.

## Auth & nesting

`auth/` authenticates RPC links (Diffie-Hellman via `moat.lib.diffiehellman`;
see `moat-link/ARCHITECTURE.md` `Hello` handshake). `nest.py` implements
`rpc_on_rpc` — tunneling one RPC connection through another (used for
multi-hop device reach-through).

## Consumers

- `moat.link` — clients and server converse over `std-cbor`-framed RPC
  (`link/conn.py`, `link/server/_server.py`).
- `moat.micro` — host `MsgSender` ↔ device `RootCmd` over the reliable CBOR
  stream; device apps/parts are `BaseCmd` subclasses.
- `moat.ems` battery — `RootCmd(...).sub_at(bat)` to reach a BMS.
- `moat.kv` — client/server framed protocol built on the same primitives.
