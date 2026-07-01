# Architecture — moat.lib.pid

Advanced PID controllers for physical-process regulation.

## Implementation (`pid/_impl.py`)

Classes:
- **`PID`** — base proportional/integral/derivative controller.
- **`CPID`** — cascade-capable variant.
- **`PID_TC`** — temperature-compensated variant.

Features: derivative filtering (noise rejection), anti-windup (integral
clamping/back-calculation), and state save/restore (so a controller can be
snapshotted and resumed across restarts or transferred between devices).

## Consumers

- `moat.dev` heater controllers (`dev/heat/solvis.py`) use PID for mixing-
  valve / circuit regulation.
- `moat.micro.part.pid` exposes a PID as a MicroPython device part
  (reachable over RPC) — see `moat-micro/ARCHITECTURE.md`.

The same controller logic thus runs on the host (driving a remote actuator
over the link) or directly on the MCU part, depending on topology.
