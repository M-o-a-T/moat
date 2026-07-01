# Architecture — moat.lib.ring

Fixed-size byte ring buffer with overwrite semantics.

## Implementation (`ring/_impl.py`, `ring/aio.py`)

A circular byte buffer that, when full, **overwrites the oldest data** rather
than blocking or growing. `aio.py` adds an async-interface wrapper (read/write
tasks awaiting free space / available data, but bounded by the fixed capacity).

## Use case

Capturing recent serial traffic or log output for diagnostic retrieval — you
want the *last* N bytes, not all bytes. Overwrite semantics guarantee bounded
memory regardless of how long the producer runs. The MicroPython console/log
tap and serial-monitor paths use this to expose a rolling tail to the host.
