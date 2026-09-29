# Plan: moat-aqu — overridable `time()` / `monotonic()` and codebase conversion

Issue: **moat-aqu** — “moat.util.time: overridable time() and monotonic();
convert codebase”. Revised per review **moat-lom**.

Goal: give tests and simulated runs a controllable clock for **wall** time
(the part trio’s `MockClock` does *not* fake) and a sane story for monotonic
time. Persisted timestamps, schedules, and comparisons with MoaT-Link message
timestamps all need a fakeable wall clock.

Acceptance criteria (verbatim):

> `moat/util/time.py` documented and typed; tests show both functions can be
> overridden and restored; no remaining direct `time.time()` /
> `time.monotonic()` calls in `moat/` except inside `moat/util/time.py` (or
> with a documented reason).

---

## Design decisions (revised after moat-lom)

### D1 — Override mechanism

Adapts the module-global-slot idea from `moat/util/random.py` (which holds a
swappable `_rand_choices` binding). NOTE (per review): `random.py` has no
set/patch API — it only picks the binding at import — so this is an
*extension* of that pattern, not a mirror of it.

`moat/util/time.py` exposes:

- `time() -> float` — wall-clock seconds (slot defaults to stdlib `time.time`).
- `monotonic() -> float` — monotonic seconds (slot defaults to stdlib
  `time.monotonic`). Kept for **loop-less** code only (see D2).
- `loop_time() -> float` — `anyio.current_time()`, falling back to the
  `monotonic()` slot when no event loop is running (`RuntimeError`). Promoted
  out of `moat/kv/mock/mqtt.py::tm()` (Blocker 1).
- `set_clock(*, time=None, monotonic=None) -> None` — permanently replace one
  or both slots; passing `None` for a slot resets it to the stdlib default.
- `patch_clock(*, time=None, monotonic=None)` — `contextmanager` that saves
  the current slots, applies the overrides, and restores them on exit
  (including on exception / cancellation — plain `try/finally` propagates
  `Cancelled` correctly; no special-casing needed).

Implementation detail (per review): inside `moat/util/time.py` the stdlib
module is imported **as `_time`** (`import time as _time`) so the `time` /
`monotonic` *parameter names* of `set_clock`/`patch_clock` cannot shadow the
stdlib reference used to reset defaults. Slots `_time_fn` / `_mono_fn` are
module-private; public `time()`/`monotonic()` delegate.

Why global slots, not threaded state: existing callsites `time.time()` become
`mtime.time()` with no plumbing; the override is process-global and scoped by
`patch_clock`. This also fixes a latent global-pollution bug in the existing
ad-hoc monkeypatch (`tests/moat_link/test_cmd_data.py` mutates stdlib
`time.time` itself — see D6).

### D2 — Wall vs monotonic, and the async-monotonic rule (Blocker 2)

REVISED (post-review-feedback): the original plan routed async monotonic
readers to `anyio.current_time()`. That was wrong — it fragments the control
surface (those sites become unreachable via `patch_clock`) and defeats the
issue's central ask of an *overridable* `monotonic()`. The synchronisation
concern that motivated it is already handled by `loop_time()`: a test does
`patch_clock(monotonic=loop_time)` and `mtime.monotonic()` then delegates to
`anyio.current_time()` *through the slot*, staying in sync with `anyio.sleep`
while remaining overridable.

Corrected rule (uniform):
- **Wall clock** (`time.time()` → `mtime.time()`): converted everywhere,
  sync or async — anyio/trio offer no fakeable wall clock; this is the issue's
  core.
- **Monotonic clock** (`time.monotonic()` → `mtime.monotonic()`): converted
  *everywhere*, sync or async alike. Overridability is uniform; tests wanting
  loop-synced monotonic time patch the slot to `loop_time`.
- **Pre-existing `anyio.current_time()` sites** (≈30, in `dev/sew`, `ems/inv`,
  `kv/gpio`, `lib/mqtt`, `lib/stream`, `link/cmd/raw`, `link/gpio`,
  `link/metrics`, `link/server`, `modbus/client`, `bus/serial`, …): LEFT
  AS-IS. They are out of this issue's scope (not `time.monotonic()` calls) and
  already ride the fakeable loop clock; converting them is unnecessary scope
  creep.

`t_iter.time()` in `moat/util/times.py` switches to `mtime.monotonic()`
(formerly mixed real `time.monotonic()` with `anyio.sleep` — now uniformly
overridable; a test patches the slot to `loop_time` to sync with `sleep`).

### D3 — Device boundary (MicroPython) — exclusions

Of all conversion targets, two are shared with MicroPython and are
**excluded** with documented reasons (acceptance allows “…or with a
documented reason”):

1. **`moat/micro/app/_sys.py`** — symlinked into the device tree as
   `_embed/lib/app/_sys_.py`. Uses `time.time()` only to report the device’s
   wall clock back over RPC (`t`/`ms`/`us`). Per review it *does* run under
   CPython in micro tests, but its purpose is to expose the (simulated)
   device’s RTC, not a host value tests need to steer; importing
   `moat.util.time` would force freezing an extra module into device firmware
   for one info field. Inline comment documents this.
2. **`lib/pid/_impl.py`** — `moat/lib/pid` is a *directory* symlink into the
   device tree; the file has a dual import (`from time import ticks_ms as
   time` on MicroPython, `from time import monotonic as time` on CPython).
   Rewiring to `mtime.monotonic()` would again require shipping
   `moat.util.time` to the device and would break the MicroPython branch.
   Left as-is with an inline comment.

Everything else is pure CPython and convertible.

### D4 — `moat/util/times.py`

- `now()`: `dt.datetime.now().astimezone()` →
  `dt.datetime.fromtimestamp(mtime.time(), dt.UTC).astimezone()`. Equivalent
  for real clocks (`fromtimestamp` sets the DST fold; matches `ts2iso`’s
  existing UTC-then-astimezone form, per review). Lets the wall clock be
  mocked — the stated aim (“`moat.util.times.now()` should use the new
  `time()` as well”). Import-time `startup = dt.datetime.now()...` stays on
  the real clock (fine).
- `t_iter.time()`: `time.monotonic()` → `anyio.current_time()` (D2).
- `ts2iso()` delta: `time.time()` → `mtime.time()`.
- Replace `import time` with `from moat.util import time as mtime` (and add
  `import anyio` if not present for `t_iter`).

### D5 — Export wiring (Blocker 3 — FIXED)

**Empirically verified**: adding `"time": "time"` to
`moat/util/__init__.py::_imports` makes `from moat.util import time as mtime`
return the *function* on first access (the lazy `__getattr__` fires and
shadows the submodule), breaking every converter. Confirmed with a throwaway
loader replica.

Fix: **do NOT add the keys `time` or `monotonic`** to `_imports`. The
submodule `moat.util.time` then resolves naturally and
`from moat.util import time as mtime` yields the module (verified).

Optionally add the non-colliding callable names for ergonomic flat access:
`"set_clock": "time"`, `"patch_clock": "time"`, `"loop_time": "time"`. These
keys do not collide with the submodule name and resolve via the existing
relative-import loader (`__import__("time", …, level=1)` → `moat.util.time`).
Direct `from moat.util.time import …` works regardless.

### D6 — Update existing mocks

1. `tests/moat_link/test_cmd_data.py::test_load_force_retries_with_start_timestamp`
   currently does `monkeypatch.setattr(data_cmd.time, "time", lambda: 9999.25)`
   — which mutates the **stdlib** `time.time` globally. Rewrite to
   `with mtime.patch_clock(time=lambda: 9999.25):` wrapping the test body.
   Fixes the global pollution and demos the new API.
2. `moat/kv/mock/mqtt.py` (Blocker 1): replace the two
   `mock.patch("time.time", new=tm)` / `mock.patch("time.monotonic", new=tm)`
   `enter_context` calls with a single
   `ex.enter_context(mtime.patch_clock(time=mtime.loop_time, monotonic=mtime.loop_time))`.
   Delete the local `tm()`/`otm` definitions (their job moves to
   `mtime.loop_time`). Rationale: once MoaT callers route through `mtime`,
   the global stdlib patch no longer reaches them; `patch_clock` does.
   Risk: any *third-party* code (amqtt/asyncscope) reading stdlib
   `time.time` reverts to real time. `moat/mqtt` has no such reads (audited);
   if a kv test regresses, fall back to keeping the global patch alongside
   `patch_clock` and note it. Decide empirically in Step 4.

### D7 — `datetime.now()` wall-clock reads (review smaller-point)

Audited 26 `datetime.now()`/`dt.datetime.now()` sites in `moat/` (non-embed).
They bypass the fakeable wall clock and thus defeat the goal, but are
**outside the issue’s literal acceptance** (“`time.time()`/`time.monotonic()`”
only). Policy:

- In files **already touched** by Step 3, convert obvious wall-clock-for-
  timestamp `datetime.now(UTC)` → `dt.datetime.fromtimestamp(mtime.time(),
  dt.UTC)` opportunistically (low marginal cost): `link/server/_server.py`
  (1437/1445/1452/1822/1824), `kv/cal/util.py`, `link/cal/util.py`,
  `util/_main.py`, `util/times.py`.
- Standalone `datetime.now()` files **not** otherwise touched
  (`db/rain/monitor.py`, `ems/inv/__init__.py`, `mqtt/mqtt/packet.py`,
  `mqtt/plugins/sys/broker.py`, `dev/heat/solvis.py:1688`,
  `kv/command/dump/__init__.py`): **file a follow-up beads issue** rather
  than expand this change. Documented here.

### D8 — Import-alias strategy for converters

`from moat.util import time as mtime` (short alias; avoids shadowing stdlib
`time` where a file still needs `time.sleep`/`time.clock_gettime_ns`).

- Files using `time.time()`/`time.monotonic()` **and** other stdlib `time.*`
  members keep `import time` alongside `mtime` (e.g. `solvis.py` keeps
  `time.sleep`; `gpio/_impl.py` keeps `time.clock_gettime_ns`/
  `CLOCK_MONOTONIC`).
- Files using only `time.time()`/`time.monotonic()` drop `import time`.
- Files whose only `time` use is `from time import time`/`monotonic` switch to
  `from moat.util import time as mtime` and call `mtime.time()`/…
  (`kv/errors.py`, `util/_main.py`, `priomap/_impl.py`).
- Async-monotonic converters add/use `anyio.current_time()` (ensure
  `import anyio`).

Quick per-file check that the name `mtime` is unused before adopting it.

---

## Steps

### Step 1 — New module + tests (isolatable, provable first)

- [ ] Create `moat/util/time.py` per D1: `import time as _time`; slots
  `_time_fn`/`_mono_fn`; `time()`,`monotonic()`,`loop_time()`,
  `set_clock()`,`patch_clock()`; `__all__`; full typing (no `Any`/casts/
  `type:ignore` unless ty insists and no alternative).
- [ ] Wire D5: add `set_clock`/`patch_clock`/`loop_time` to `_imports`
  (**never** `time`/`monotonic`).
- [ ] `tests/moat_util/test_time.py`: defaults sanity; `set_clock` overrides
  each independently + resets via `None`; `patch_clock` restores on normal
  exit and on exception; partial override (patch `time` only); `loop_time()`
  returns ≥0 outside a loop (fallback) and inside trio advances with
  `anyio.sleep`.
- [ ] `ty check` clean; pytest green (logs to temp file, inspect via tmux).

### Step 2 — Convert `moat/util/times.py` (D4) + `moat/util/_main.py`

- [ ] `times.py`: `now()`, `t_iter.time()`→`anyio.current_time()`, `ts2iso`.
- [ ] `util/_main.py:100` `time()` → `mtime.time()` (drop `from time import
  time`).
- [ ] Re-run `tests/moat_util/` (test_times + test_time).

### Step 3 — Mechanical conversions, batched by subtree (counts corrected)

Counts from the full audit (form-aware: incl. `from time import …` and
`= time.time` aliases):

- [ ] **link/** — **16 files**: `_data.py`, `_test.py` (drop `otm`),
  `backend/mqtt.py`, `client.py`, `cmd/data.py`, `cmd/error.py`,
  `cmd/raw.py`, `flow/_main.py`, `gate/__init__.py`, `host.py`,
  `job/_main.py`, `job/runner.py`, `meta.py`, `notify/__init__.py`,
  `schema/_main.py`, `server/_server.py`. Apply D2 table for monotonic;
  opportunistic `datetime.now()` per D7 in `server/_server.py`.
- [ ] **kv/** — **5 direct + 1 mock**: `command/data.py`, `command/job.py`,
  `data.py`, `runner.py`, `server.py`, plus `errors.py` (`from time import
  time`), plus `mock/mqtt.py` (D6.2 helper migration, no direct call).
- [ ] **ems/** — 2: `sched/_main.py`, `sched/control.py`.
- [ ] **bus/fake/** — 2: `bus.py` (sync→`mtime.monotonic()`), `client.py`
  (async→`anyio.current_time()`).
- [ ] **modbus/** — 1: `server.py` (async→`anyio.current_time()`).
- [ ] **dev/heat/** — 1: `solvis.py` (keeps `import time` for `time.sleep`;
  D7 leaves its `datetime.now` for the follow-up).
- [ ] **lib/** — 2: `gpio/_impl.py` (keeps `import time` for
  `clock_gettime_ns`/`CLOCK_MONOTONIC`; `time.time()`→`mtime.time()`),
  `repl/commands.py`, `priomap/_impl.py` (`from time import monotonic as
  time` → `mtime.monotonic()`).
- [ ] **micro/** — 1: `micro/_main.py` (`from time import monotonic as tm` →
  `anyio.current_time()`; async elapsed-time). **Excluded**: `micro/app/_sys.py`
  (D3) — add inline comment.

### Step 4 — Update mocks (D6)

- [ ] `tests/moat_link/test_cmd_data.py` → `patch_clock`.
- [ ] `moat/kv/mock/mqtt.py` → `patch_clock(loop_time…)`, delete `tm`/`otm`.
- [ ] Run `tests/moat_kv/` (esp. mqtt-backed tests) to validate Blocker-1 fix;
  if regression, keep global patch too and note.

### Step 5 — Verification sweep (audit catches all equivalent forms)

- [ ] Form-aware grep returns only `moat/util/time.py` internals + the two
  documented exclusions (`micro/app/_sys.py`, `lib/pid/_impl.py`):
  `git grep -nE "time\.(time|monotonic)\(\)|from time import (time|monotonic)" -- 'moat/*.py' ':!moat/micro/_embed/*'`
  plus `= time\.(time|monotonic)\b` aliases.
- [ ] `ty check --output-format github` clean repo-wide.
- [ ] Pytest touched subtrees: `tests/moat_util/`, `tests/moat_link*/`,
  `tests/moat_kv/`, `tests/moat_bus/`, `tests/moat_modbus/`,
  `tests/moat_lib_priomap/`, `tests/moat_micro/`. Logs to temp files.
- [ ] Pre-commit (formats + ty + per-module tests) green on commit.

### Step 6 — Follow-ups + hygiene

- [ ] Create follow-up beads issue for the standalone `datetime.now()` sites
  (D7 list) — fakeable wall clock via `mtime.time()`.
- [ ] Spot-check `moat/util` packaging README for a submodule list; update
  only if it enumerates submodules.

---

## Risks / notes

- **Blocker 1 regression window**: removing the kv mock’s global stdlib
  patch could let third-party `time.time` readers see real time in autojump
  tests. Audited `moat/mqtt` (none); amqtt/asyncscope unknown — Step 4
  decides empirically, with a documented fallback.
- **`link/server/_server.py`** greps show `time.now`/`time.desc` etc. — those
  are SQLAlchemy column attrs / locals, not stdlib; only genuine
  `time.time()`/`time.monotonic()`/`datetime.now()` are retargeted.
- **`lib/pid/_impl.py`** exclusion is structural (device-shared dual import),
  not laziness; the follow-up could add a `moat.util.time` MicroPython stub
  if device-side fakeability is ever wanted.
- **Out of scope**: `time.time_ns()` (`link/metrics/backend/victoria`) and
  `time.monotonic_ns()` (`lib/micro/__init__.py`) — not in the issue’s
  ~51/~14 counts; leave (follow-up can add `*_ns` to `moat.util.time`).

## Review checkpoint

Plan revised to address all three moat-lom blockers (kv-mock helper promotion,
async-monotonic→`anyio.current_time()`, lazy-loader key collision) and the
smaller points (random.py wording, `_time` alias, missed import-equivalent
forms, count corrections, `datetime.now()` policy). moat-lom remains the
blocking review; reopen/continue it after this revision is committed.
