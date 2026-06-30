# Architecture — moat.bus

Sans-IO, multi-wire (2–6 wire) hardware bus protocol with collision detection,
CRC, priority arbitration, and ACK/NACK. The low-level embedded/IoT transport
layer.

## Core (`bus/handler.py`, `message.py`, `crc.py`, `serial.py`, `util.py`)

- **`BaseHandler`** (`handler.py:62`) — the core **sans-IO state machine**.
  States in `S` (IntEnum: IDLE, READ, WRITE, READ_ACK, …), errors in `ERR`,
  results in `RES`. Users override `set_timeout`, `set_wire`, `get_wire`,
  `process`, `report_error`, `transmitted`. Handles send queuing (priority +
  normal), wire-change processing, collision recovery with exponential
  backoff.
- **`BusMessage`** (`message.py:29`) — `src`/`dst` (7-bit or 3-bit short
  addresses), `code`, `prio`, bit-array `_data`. Chunk extraction/addition
  for the wire protocol; header parsing.
- **`CRC11`/`CRC6`/`CRC8`/`CRC16`/`CRC32`** (`crc.py`) — table-driven CRC via
  metaclass `_CRCmeta`.
- **`SerBus`** (`serial.py:42`) — alternative sans-IO serializer for carrying
  bus messages over a serial line (with `CRC16`, framing, ACK bytes).
- **Minifloat** (`util.py`) — byte-sized float encoding for compact timeout
  representation in messages.

## Subdirectories

- **`backend/`** — transport adapters. `BaseBusHandler` base
  (`backend/__init__.py`); concrete: `mqtt.py`, `serial.py`, `moat_kv.py`,
  `_stream.py`.
- **`server/`** — bus server. `Server` (`server/server.py`) with `ClientStore`
  for address assignment, `Obj` (`obj.py`), `gateway.py`; CLI in
  `_main.py`.
- **`fake/`** — test/mock implementations (`bus.py`, `client.py`, `send.py`,
  `recv.py`, `seq.py`).

## Integration

Relatively self-contained. Historical quirk: `message.py` imports `attrdict`
from `distkv.util` rather than `moat.util`, and `server/` uses a local
`CtxObj`/`Dispatcher` from `moat.bus.util` (not `moat.util`) — evidence of its
origin as a separate project. Backend handlers integrate with the
nursery/task-group model. Device drivers in `moat.dev` communicate over this
bus.

## Design rationale

**Sans-IO protocol cores** (`BaseHandler`): the state machine owns no I/O —
it calls back into overridden `set_wire`/`get_wire`/`set_timeout`. This makes
the protocol testable without hardware and transport-independent (the same
core runs over GPIO wires, serial, MQTT, or KV backends).
