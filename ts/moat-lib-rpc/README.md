# @moat/lib-rpc

TypeScript port of MoaT's `moat.lib.rpc` — wire-compatible CBOR RPC with Python interop.

<!-- SYNOPSIS -->

Sans-IO core with async client/server, speaking the same wire protocol as the
Python `moat.lib.rpc` library. Uses CBOR (via `cbor2`) with MoaT's standard
extension tags. Supports WebSocket and TCP transports, with TypeScript↔Python
interoperability over the wire.

<!-- /SYNOPSIS -->

# Main

## Installation

```bash
npm install @moat/lib-rpc
```

## Quick Start

### Server

```typescript
import { MsgHandler, RpcServer } from '@moat/lib-rpc';

class MyHandler extends MsgHandler {
  async cmd_ping() { return 'pong'; }
  async cmd_add(a: number, b: number) { return a + b; }
}

const server = new RpcServer(new MyHandler());
await server.listenWs(8080);
```

### Client

```typescript
import { RpcClient } from '@moat/lib-rpc';

const client = await RpcClient.connectWs('ws://localhost:8080');
const pong = await client.cmd('ping');     // → 'pong'
const sum = await client.cmd('add', 3, 4); // → 7
await client.close();
```

## Architecture

- **Sans-IO core** (`RpcCore`): pure synchronous state machine — no promises,
  timers, or I/O. Testable with deterministic step sequences.
- **Async adapter** (`AsyncAdapter`): bridges the core with Promises/timers,
  owns the id reuse-delay timer (~1s, matching Python's L-build behaviour).
- **Transports**: WebSocket (binary frames = CBOR), TCP (incremental CBOR
  decode), pipe (stdin/stdout for interop tests).
- **Codec**: `cbor2` with MoaT extension tags (Path=39, DProxy=27,
  Proxy=32769, Set=258, Date=1/0).

## Wire Protocol

Each RPC message is one CBOR array: `[header, *args, ?kwargsMap]`.

The header integer packs the sub-channel id and flags using arithmetic
(`id*4 + flag`), not 32-bit shifts (which overflow at id > 2²⁹).

Positive ids are allocated by the originator; the responder sees them as
negative (sign-flipped on receive) and reuses the negative id in replies.

## License

MIT — deliberate relicensing of LGPL v3 derived code by the copyright holder.
