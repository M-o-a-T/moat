# Architecture — moat.lib.micro

The CPython/MicroPython compatibility shim. Its docstring: *"Compatibility
wrappers that allow MoaT code to run on CPython/anyio as well as
MicroPython/uasyncio."* Nearly every subsystem imports from here.

> There is **no module literally named `moat.lib.compat`** — `moat.lib.micro`
> fulfills that role (AGENTS.md refers to "compatibility code in
> `moat.micro.compat`", meaning this). A legacy `TODO/bus/python/moat/compat.py`
> exists but is unused.

## Bridging strategy (`lib/micro/__init__.py`)

- **Neutral re-exports of anyio primitives** so callers never import anyio
  directly: `Event`, `Lock`, `WouldBlock`, `EndOfStream`, etc. Callers write
  `from moat.lib.micro import Event, Lock, Queue, sleep`.
- **Normalized exceptions**: `Queue` subclasses `moat.util.Queue` and
  translates anyio's `EndOfStream`→`EOFError`, `WouldBlock`→`QueueEmpty`/
  `QueueFull` — matching MicroPython `uasyncio` semantics.
- **MicroPython-style APIs on CPython**: `ticks_ms()` (monotonic ns÷1e6),
  `sleep_ms`, `wait_for_ms`, `every_ms`/`every`, `retry_ms`/`retry`,
  `const()` (no-op mirroring µPy `micropython.const`), `byte2utf8`.
- **Augmented TaskGroup**: `TaskGroup()` dynamically subclasses the backend
  TaskGroup adding `spawn()` (returns a cancellable `CancelScope`, unlike
  plain `start()`) and `cancel()`. The subclass is cached globally.
- **Owns the `ACM`/`AC_use`/`AC_exit` lifecycle system** — a per-object stack
  of `AsyncExitStack`s with cross-task ownership guarding (`_ac_check_owner`).
  This is the consistent resource-management convention used throughout MoaT
  *instead of* raw `async with`.
- **Dual awaitability**: `rpc.base.Caller` implements both `__await__`
  (CPython) and `__iter__` (MicroPython, relying on µPy's native coroutine
  iteration) — explicitly noted as "depends on µPy doing the right thing."

## Provided primitives

`TaskGroup` (with `spawn`/`cancel`), `Queue`, `Event`, `Lock`, `CancelScope`,
`sleep`/`sleep_ms`, `ticks_ms`/`ticks_add`/`ticks_diff`, `wait_for[_ms]`,
`every[_ms]`, `retry[_ms]`, `shield`, `run`, `run_server`, `to_thread`,
`is_async`, `ACM`/`AC_use`/`AC_exit`, `idle`, `log`.

## Consumers

`lib/run/__init__.py`, `lib/stream/base.py`, `lib/rpc/base.py`,
`lib/broadcast/_impl.py`, `lib/config/_impl.py` all import from here. The
embedded MicroPython side (`moat/micro/_embed/lib/moat/lib/micro/`) mirrors
this API so host and device share RPC code (see `moat-micro/ARCHITECTURE.md`).

## Design rationale

One async vocabulary across two runtimes. MicroPython is patched so the C
`Task` is hashable (needed for taskgroups); `moat.lib.micro` papers over the
remaining differences, letting the same RPC/stream/codec code run on both
sides of the serial link.
