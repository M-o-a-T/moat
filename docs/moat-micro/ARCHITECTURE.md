# Architecture — moat.micro

MicroPython device integration: a single serial/TCP connection carries a
reliable bidirectional CBOR RPC between host and satellite MCU
(`micro/_embed/README.md`). Framing + an X.75-style reliability layer handle
unreliable serial. MicroPython is patched (the C `Task` must be hashable) so
taskgroups work; `moat.lib.micro` provides the same `TaskGroup.spawn`/`ACM`
API on both sides, so host and device share RPC code.

## Embedded side (`micro/_embed/`)

Boot chain:
- `boot.py` — sets up USB-CDC serial; runs `boot_local.py` if present.
- `main.py` — calls `moat.go()` → `go_.py:go()`.
- **`go_.py:go(state=None, cmd=True)`** — selects a boot state
  (`flash`/`rom`/`std`/`safe`/`norom`/`once`/`skip`), persisted to RTC. States
  control `sys.path` composition (which of `/lib`, `/rom`, `.frozen` are
  used) for fallback resilience. On crash, advances to the next state and
  `machine.soft_reset()`. Then calls `micro/main.py:main()`.
- **`micro/main.py:main(cfg, i, fake_end=False)`** — loads CBOR config (from
  file or dict), merges RTC overrides, starts the hardware watchdog early,
  brings up networking (`network.WLAN`), and runs configured apps under a
  `TaskGroup`. Errors land in `wr_exc` (stderr + `moat.err` on flash).

## Apps & parts

Device apps are RPC command trees subclassing `moat.lib.rpc.BaseCmd`
(`micro/app/_base.py`, `_sys.py`).

- **`micro/app/`** — apps: `stdio`, `serial`, `i2c`, `spi`, `wdt`, `ping`,
  `fs`, `cfg`, `log`, `pipe`, `fake`, `bms`, `ic`, plus `rtc.py`
  (RTC-backed key store) and `_sys.py` (eval/unproxy/test introspection).
- **`micro/part/`** — reusable components composed into apps: `pid`, `relay`,
  `pwm`, `control`, `average`, `transfer`, `pin`, `noop`, `fake`, `serial`.
  `micro/app/part.py` is a lazy loader mapping attr→module.
- Apps register under the `moat.micro.app` namespace via `add_app_prefix`
  (`micro/__init__.py`), so RPC paths like `moat.micro.app.serial.…` resolve.

The embedded library lives at `micro/_embed/lib/` with a mirrored `moat/`
tree (`moat/lib/{rpc,stream,micro,…}`, `moat/micro/{main,console,…}`,
`moat/util/`) — much of it symlinked to the host source so the two sides
share code. `lib/serialpacker.py` and `lib/mpdb.py` are linked in.

## Host side (`micro/_main.py`)

`moat micro` CLI. Subcommands:
- **`run`** — server mode (the host acts as the link endpoint).
- **`setup` / `install`** — initial file sync via raw REPL.
- Runtime commands — talk to a running satellite over the configured
  `connect` section (default remote prefix `r`).

Options: `-S/--section` (config section: `run`/`setup`/`connect`),
`-R/--remote` (path for talking to the satellite), `-P/--path` (named remote
component).

Key host modules:
- **`micro/direct.py:DirectREPL`** (`SingleAnyioBuf`) — talks the raw
  MicroPython REPL for bootstrap (escapes special modes, evaluates code,
  collects output). Used before the MoaT protocol is installed.
- **`micro/setup.py`** — uploads `boot.py`/`main.py` + frozen libs; `do_update`
  copies the embed tree; `do_copy` syncs arbitrary trees.
- **`micro/files.py`** — async `APath`/`ABytes`/`copytree` over the MoaT file
  protocol (RPC-based filesystem access). `APath` works against either a
  local dir or a remote device uniformly.
- **Incremental updates** — `run_update` (in `micro/util.py`) uses
  cross-compilation (`mpy-cross`) and content hashing to ship only changed
  `.mpy` files.

## Control / data flow

Host `moat micro <cmd>` opens a serial/TCP transport → wraps in the
`moat.lib.stream` reliable CBOR message layer → `MsgSender` exchanges
`moat.lib.rpc.Msg` with the device → device `RootCmd` dispatches to the
addressed app/part; `Caller` awaits results (dual `__await__`/`__iter__`).

Console channels `cwr`/`crd` (out-of-band on the stream) carry the device
REPL/debug log alongside the RPC data, so `moat micro` can show device
output without a second wire.

## Entry points

- Device: `micro/_embed/main.py` → `moat.go()` → `go_.py:go` →
  `micro/main.py:main`. (`main_unix.py` for the unix MicroPython port.)
- Host: `moat micro {run,setup,install,<cmd>}` (`micro/_main.py`).
- Library: `moat.lib.micro.main` (host-side link helpers), `micro.util`
  (`run_update`, `TEST_MAGIC`).
