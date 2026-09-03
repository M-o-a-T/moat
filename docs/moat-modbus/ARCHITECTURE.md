# Architecture -- moat.modbus

Opinionated async Modbus client + server for both Modbus-TCP and Modbus-RTU
(serial). Builds on `moat.lib.modbus` (a sans-IO protocol core, stdlib-only)
for PDU encoding/decoding and framing, then reimplements connection
management and polling on top of anyio. `__init__.py` describes it as
"an opinionated async Modbus client and server."

## Client (`modbus/client.py`)

- **`ModbusClient`** -- top-level container/registry of `hosts`. Async ctx mgr
  (`CtxObj`) spawning a task group. `host()` (TCP), `serial()` (RTU),
  `conn(cfg)` (config-driven dispatch); `*_service()` variants run connections
  as background tasks via `task_status.started()`.
- **`HostCommon`** -- base for `Host`/`SerialHost`. Manages transactions
  (`_transactions` keyed by TID), write queue, capacity limiter (`cap`), send
  lock, `_connected` event. `execute(request)` builds a frame, sends, awaits
  a `ValueEvent` reply matched by `transaction_id`.
- **`Host`** (TCP, `FramerTCP(False)`) -- `_reader()` connects via
  `anyio.connect_tcp`, sets SO_LINGER for RST, re-sends open transactions on
  reconnect, decodes frames, resolves by TID. Reconnect-with-delay.
- **`SerialHost`** (RTU, `FramerRTU(False)`) -- `_reader()` opens
  `anyio_serial.Serial`; optionally routes replies through a `monitor`
  callback (passive sniffing) instead of TID matching. TID always 0.
  Uses `RTU_INTER_FRAME_TIMEOUT` (~0.2 s) to detect stale partial frames:
  when the framer accumulator is non-empty, the next `receive()` is wrapped
  in `anyio.fail_after(RTU_INTER_FRAME_TIMEOUT)`; on `TimeoutError`,
  `resetFrame()` is called and the loop continues (connection stays up).
- **`Unit`** — one slave address under a host; owns `Slot`s; stamps
  `unit_id` and forwards to `host.execute()`.
- **`Slot`** — an "atomic access" group polled at a common cadence. Holds
  `modes: dict[TypeCodec, ValueList]`. Runs `read_task` (periodic reads with
  alignment/backoff/staleness via `read_if_stale`) and `write_task` (collated
  writes via `write_trigger`). Tracks `mqtt_registers` for change-notification
  toward the link. `getValues()`/`setValues()` fan out in parallel across
  modes.
- **`ValueList`** (`DataBlock`) — per-`TypeCodec` collection; computes
  contiguous register ranges (capped by `max_rd_len`/`max_wr_len`), issues
  `readBlock`/`writeBlock` concurrently, decodes into `BaseValue`s.
- **`ModbusError`** — wraps an error response.

## Server (`modbus/server.py`)

- **`BaseModbusServer`** — holds a `ModbusServerContext`, units registry,
  `ModbusControlBlock`, identity, `ignored` set. `process_request()` dispatches
  to a unit's `process_request` or falls back to `update_datastore`.
- **`ModbusServer`** (TCP) — `serve()` binds a TCP listener
  (`anyio.create_tcp_listener`), serves each connection in `_serve_one`,
  frames with `FramerSocket`, handles `NoSuchSlaveException`/timeouts with
  `ExceptionResponse`.
- **`SerialModbusServer`** (RTU) — reads from `anyio_serial.Serial`, resets
  frame on inter-frame gaps (>0.2 s), processes via `_process()`, handles
  broadcast, writes framed responses.
- **`RelayServer`** — mix-in forwarding every request to a backing
  `client.execute()` (transparent gateway); `mon_request`/`mon_response`
  hooks.
- **`UnitContext`** (`ModbusDeviceContext`) — slave context backed by four
  `DataBlock`s (di/co/ir/hr); `add(typ, offset, val)` registers typed values.
- **`create_server(cfg)`** — factory selecting TCP vs serial by cfg keys.

## Types (`modbus/types.py`)

`TypeCodec` singletons (`Coils`, `DiscreteInputs`, `HoldingRegisters`,
`InputRegisters`) binding read/write PDU classes. `BaseValue` + subclasses
(`IntValue`, `LongValue`, `QuadValue`, `BitValue`, `FloatValue`,
`DoubleValue`, signed/swapped variants, `StringValue`, `InaccessibleValue`).
`DataBlock` (`ModbusSparseDataBlock`) — sparse values, read/write ranges,
encode/decode, `changed` event. `ValueIterator` — async iteration over value
changes (generation-counter skip detection).

## Integration with MoaT-Link (`modbus/dev/`)

- **`dev/poll.py:dev_poll(cfg, link, …)`** — orchestrator: builds a
  `ModbusClient`, starts host services, loads devices (`ClientDevice`/
  `ServerDevice` in `dev/device.py`), runs each `.poll()`. Picks the Register
  factory based on whether a `link` is supplied: plain `device.Register` when
  `link is None`, else `link.Register` (`partial(Register, link=link, tg=tg)`).
  Constructs relay servers via `create_server()`; attaches client-unit
  registers into `ServerUnitContext`s for on-demand serving.
- **`dev/link.py:Register(BaseRegister)`** — bridges Modbus values ↔
  MoaT-Link. Each register carries `src` (link path to watch) and `dest`
  (link path to publish to):
  - `to_link(dest)` — awaits `mqtt_event` (set by the slot's `read_task` when
    `reg._changed` flips), then `self._link.d_set(dest, val)`.
  - `from_link(mon)` — `self._link.d_watch(src)`, applies transforms/idle
    filtering, writes received values to Modbus (`_set`).
  - `from_link_const` — `const: !P` paths update the read side only (server-
    served constant mirrors).
  - Server-side registers (`is_server=True`) use `_watch_datablock_changes` to
    observe `block.changed` and fire `mqtt_event`.

Coupling is through the `moat.link` client (`d_set`/`d_get`/`d_watch`); the
slot's polling loop is the change-detector driving link publication.
(`mqtt_event`/`mqtt_registers` names refer to the link change-notification
mechanism, not direct `moat.mqtt` use.)

## Entry points

CLI: `modbus/__main__.py`, `modbus/_main.py` — `mk_client`/
`mk_serial_client`/`mk_server` Click groups + a `monitor`/relay tool.
`_compat.py` monkeypatches pymodbus 3.9 where needed.
