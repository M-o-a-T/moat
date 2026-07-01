# Architecture — moat.lib.broadcast

Pub/sub fan-out primitive for status/state distribution.

## Implementation (`broadcast/_impl.py`)

- **`Broadcaster`** — a publisher holding a set of readers. `publish(value)`
  pushes to every reader's queue.
- **`BroadcastReader`** — a subscriber with a bounded queue. Iterates values
  asynchronously.

Overflow is signaled via **`LostData`**: if a reader's queue fills (slow
consumer), the reader learns data was dropped rather than blocking the
publisher or unbounding memory. This is the standard backpressure/loss
tradeoff for telemetry-style streams where freshness matters more than
completeness.

## Consumers

Used wherever a producer must fan state to multiple consumers without
coupling them: status broadcasts, monitor feeds, and the link layer's
`write_monitor` notification fan-out (see `moat-link/ARCHITECTURE.md`).
