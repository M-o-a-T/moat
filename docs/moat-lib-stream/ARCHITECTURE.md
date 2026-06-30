# Architecture — moat.lib.stream

Layered async transport abstraction: byte buffers → framed blocks → messages,
with stacking connectors for TCP/Unix/WebSocket/serial, plus reliability/
retransmission and console multiplexing.

## Files

- `base.py` — the layered base classes and stacking mixins.
- Connectors: `anyio.py`, `tcp.py`, `unix.py`, `ws.py`, `serial.py`.
- `reliable.py` — reliability/retransmission layer (X.75-style selective ACK).
- `cbor.py` — CBOR message framing.
- `log.py`, `terminal.py` — logging tap and terminal/console muxing.

## Class hierarchy (`base.py`)

Three layers, each with a `Stacked*` mixin variant:

- **`BaseBuf` / `StackedBuf`** — raw byte streams (read/write bytes).
- **`BaseBlk` / `StackedBlk`** — framed blocks (delimited byte chunks; e.g.
  `SerialPackerBlkBuf` uses the serial packer for framing).
- **`BaseMsg` / `StackedMsg`** — typed messages (encoded objects; e.g.
  `CBORMsgBuf` wires a `moat.lib.codec` onto blocks).

Connectors subclass these: `TcpLink`, `UnixLink`, `WsLink`,
`SerialPackerBlkBuf`, `ReliableMsg`, `CBORMsgBuf`.

## Contract

Build bottom-up (raw transport → buffering → framing → message encoding).
Enter as an async context manager. Hooks: `setup`/`teardown`/`stream`.
Out-of-band **console channels** `cwr`/`crd` carry a side console multiplex
alongside the data stream — used by the MicroPython link to expose the
device REPL/debug channel over the same wire (see `moat-micro/
ARCHITECTURE.md`).

## Reliability layer (`reliable.py`)

For unreliable transports (serial), `ReliableMsg` adds sequence numbers,
selective ACKs, and retransmission of lost messages while preserving order.
Modeled roughly on X.75. This is what makes the MicroPython serial RPC robust
despite line noise.

## Embedded mirror

The MicroPython side mirrors a subset (`moat/micro/_embed/lib/moat/lib/stream/`:
`reliable.py`, `cbor.py`, `serial.py`, `tcp.py`, `__init__.py`) using
symlinked/shared code so host and device speak the same framing.

## Consumers

- `moat.lib.rpc` connections sit atop a message stream.
- `moat.link` server/client RPC streams use `std-cbor`-framed messages over
  TCP/Unix (`link/conn.py`).
- `moat.micro` host↔device link is a reliable CBOR message stream over
  serial/TCP.
