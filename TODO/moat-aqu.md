# Plan: moat-aqu — overridable `time()` / `monotonic()` and codebase conversion

Issue: **moat-aqu** — “moat.util.time: overridable time() and monotonic();
convert codebase”.

Goal: give tests and simulated runs a controllable clock for **both** wall
time and monotonic time. trio’s `MockClock` only fakes the event loop’s
monotonic clock, not `time.time()`. Persisted timestamps, schedules, and
comparisons with MoaT-Link message timestamps all need a fakeable wall clock.

Acceptance criteria (verbatim):

> `moat/util/time.py` documented and typed; tests show both functions can be
> overridden and restored; no remaining direct `time.time()` /
> `time.monotonic()` calls in `moat/` except inside `moat/util/time.py` (or
> with a documented reason).

---

## Design decisions (locked in)

### D1 — Override mechanism

Follow the established `moat/util/random.py` pattern: hold the active clock
functions in module-level slots and swap them at runtime.

`moat/util/time.py` exposes:

- `time() -> float` — current wall-clock seconds (defaults to `time.time`).
- `monotonic() -> float` — monotonic seconds (defaults to `time.monotonic`).
- `set_clock(*, time=None, monotonic=None)` — permanently replace one or
  both slots (passing `None` resets to the stdlib default). Used by fixtures
  that manage their own teardown.
- `@contextmanager patch_clock(*, time=None, monotonic=None)` — restore-on-
  exit variant, the idiomatic thing tests reach for. Restores prior slots even
  on exception (uses `try/finally`; re-raises `BaseException`-but-not-
  `Exception` per house rule — actually plain `try/finally` suffices and
  preserves cancellation naturally).

Slots are module-private (`_time_fn`, `_mono_fn`). Public `time()`/
`monotonic()` delegate. This mirrors `random._rand_choices` exactly.

Why not a class/object passed around: the whole point is that *existing*
callsites `time.time()` become `mtime.time()` with no threading of state;
the override is process-global, scoped by the context manager. Matches the
precedent and the existing ad-hoc monkeypatch in `test_cmd_data.py`.

### D2 — Device boundary (MicroPython)

Survey result: of the 26 conversion-target files, **only**
`moat/micro/app/_sys.py` is mirrored into the MicroPython device tree
(symlinked as `moat/micro/_embed/lib/app/_sys_.py`). Everything else is pure
CPython.

`_sys.py` uses `time.time()` solely to report the device’s wall clock back
over RPC (`"t"`/`"ms"`/`"us"` keys). On a device there is exactly one real
wall clock and tests do not run there, so making it fakeable buys nothing but
would force shipping `moat.util.time` to MicroPython as a frozen module.

Decision: **leave `moat/micro/app/_sys.py` unchanged**, with an inline
comment citing the reason. This satisfies the acceptance criterion’s
“…except … (or with a documented reason)” clause. Recorded as a deliberate
exclusion, not an oversight.

### D3 — Import style for converters

Each converted file replaces `time.time()` → `mtime.time()` and
`time.monotonic()` → `mtime.monotonic()`, importing the new module as
`from moat.util import time as mtime` (short alias, avoids shadowing the
stdlib `time` module that some files still need for `time.sleep`,
`time.clock_gettime_ns`, etc.).

Where a file uses `time.time()`/`time.monotonic()` **and** other stdlib
`time.*` members (e.g. `solvis.py` keeps `time.sleep`; `gpio/_impl.py` keeps
`time.clock_gettime_ns`/`CLOCK_MONOTONIC`), keep `import time` alongside the
new `mtime` import.

Where a file uses **only** `time.time()`/`time.monotonic()`, drop
`import time` entirely and rely on `mtime`.

### D4 — `moat/util/times.py`

`now()` switches to `mtime.time()` via `dt.datetime.fromtimestamp(...)`.
`t_iter.time()` and `ts2iso()`’s delta computation switch to `mtime.monotonic()`
and `mtime.time()` respectively. `import time` is replaced by the `mtime`
alias. This is the one functional behavior change worth a careful look
(previously `now()` used `dt.datetime.now().astimezone()`; the new form is
equivalent and lets the wall clock be mocked, which is the stated aim:
“`moat.util.times.now()` should use the new `time()` as well”).

### D5 — Export wiring

Add `time`/`monotonic`/`set_clock`/`patch_clock` to `moat/util/__init__.py`’s
`_imports` map keyed to `"time"`, so `from moat.util import time as mtime`
works through the lazy loader. (Direct `from moat.util.time import …` also
works regardless.)

Note: `moat/util/__init__.py` shadows the stdlib name only for callers who do
`from moat.util import time` — fine, that’s the intent.

### D6 — Update the existing ad-hoc mock

`tests/moat_link/test_cmd_data.py:test_load_force_retries_with_start_timestamp`
currently does `monkeypatch.setattr(data_cmd.time, "time", lambda: 9999.25)`.
After conversion `data_cmd` no longer imports stdlib `time`; rewrite to
`patch_clock(time=lambda: 9999.25)` (or `mtime.set_clock(time=...)` with
teardown). Keeps the test green and demonstrates the new API in situ.

---

## Steps

### Step 1 — New module + tests (isolatable, provable first)

- [ ] Create `moat/util/time.py`:
  - module docstring (RST, Google-style);
  - `__all__`;
  - private slots `_time_fn`, `_mono_fn` initialized to `time.time` /
    `time.monotonic`;
  - `time() -> float`, `monotonic() -> float`;
  - `set_clock(*, time=None, monotonic=None) -> None`;
  - `patch_clock(*, time=None, monotonic=None)` context manager
    (`contextlib.contextmanager`);
  - comprehensive typing (no `Any`/casts/`type:ignore` unless ty demands and
    no alternative exists).
- [ ] Wire exports into `moat/util/__init__.py::_imports`.
- [ ] Create `tests/moat_util/test_time.py` covering:
  - defaults match `time.time`/`time.monotonic` (sanity);
  - `set_clock` overrides both independently and restores via `None`;
  - `patch_clock` overrides and restores on normal exit;
  - `patch_clock` restores on exception;
  - nesting / partial override (patch only `time`, leave `monotonic` default).
- [ ] Verify: `ty check` clean for the new file; `pytest tests/moat_util/test_time.py`
  green (write output to a temp logfile, inspect via tmux head/tail — no piping).

Definition of done for Step 1: new module lands, tests green, ty happy. This
already fulfills the “tests show both functions can be overridden and
restored” half of acceptance on its own.

### Step 2 — Convert `moat/util/times.py` (functional change, review carefully)

- [ ] Replace `import time` with `from moat.util import time as mtime`;
  adjust `now()`, `t_iter.time()`, `ts2iso()`.
- [ ] Re-run `tests/moat_util/test_times.py` (+ the new test_time) to confirm
  no regression.

### Step 3 — Mechanical conversions, batched by subtree

Apply D3 import rules. Order chosen to cluster reviews and keep diffs boring:

- [ ] **link/** (largest cluster, 13 files): `_data.py`, `_test.py`,
  `backend/mqtt.py`, `client.py`, `cmd/data.py`, `cmd/error.py`, `cmd/raw.py`,
  `flow/_main.py`, `gate/__init__.py`, `host.py`, `job/_main.py`,
  `job/runner.py`, `meta.py`, `notify/__init__.py`, `schema/_main.py`,
  `server/_server.py`.
- [ ] **kv/** (6 files): `command/data.py`, `command/job.py`, `data.py`,
  `runner.py`, `server.py`, *(skip `mock/mqtt.py` — uses MockClock, no
  `time.time`/`time.monotonic` direct call; double-check)*.
- [ ] **ems/** (2): `sched/_main.py`, `sched/control.py`.
- [ ] **bus/fake/** (2): `bus.py`, `client.py` (monotonic only).
- [ ] **modbus/** (1): `server.py` (monotonic).
- [ ] **dev/heat/** (1): `solvis.py` (keeps `import time` for `time.sleep`).
- [ ] **lib/** (2): `gpio/_impl.py` (keeps `import time` for
  `clock_gettime_ns`/`CLOCK_MONOTONIC`), `repl/commands.py`.
- [ ] **micro/app/** (1): `_sys.py` — **DO NOT CONVERT**; add inline comment
  documenting the device-boundary reason (D2).

### Step 4 — Update the existing ad-hoc test mock (D6)

- [ ] Rewrite `tests/moat_link/test_cmd_data.py` monkeypatch to use
  `patch_clock`/`set_clock`.

### Step 5 — Verification sweep

- [ ] Grep audit: `git grep -nE "time\.(time|monotonic)\(\)" -- 'moat/*.py'
  ':!moat/micro/_embed/*'` returns only `moat/util/time.py` internals +
  `moat/micro/app/_sys.py` (documented exclusion).
- [ ] Full repo `ty check --output-format github` clean.
- [ ] Targeted pytest on touched subtrees: `tests/moat_util/`,
  `tests/moat_link/`, `tests/moat_kv/`, `tests/moat_emssched/` (if present),
  `tests/moat_bus/`, `tests/moat_modbus/`. Capture logs to temp files.
- [ ] Pre-commit hook runs (formats + typechecks + tests) on commit.

### Step 6 — Docs / packaging hygiene

- [ ] Ensure `moat/util/time.py` is picked up by `[tool.ty.src] include =
  "moat/util/"` (already covered — no pyproject change expected).
- [ ] No README/doc-page update required for a util submodule unless the
  package README lists submodules; spot-check `moat/util` packaging readme.

---

## Risks / notes

- **Behavior equivalence in `times.now()`**: switching from
  `dt.datetime.now().astimezone()` to `dt.datetime.fromtimestamp(mtime.time())`
  .astimezone() is semantically identical for real clocks; flagged in D4 for
  reviewer attention.
- **`link/server/_server.py`** shows `time.now`/`time.time`/`time.monotonic`
  in greps — `time.now` there is a local/attribute, not stdlib; verify during
  conversion that only genuine `time.time()`/`time.monotonic()` calls are
  retargeted.
- **Shadowing**: files that do `from moat.util import time as mtime` must not
  already bind the name `mtime`; quick check per file during conversion.
- **Out of scope**: `time.time_ns()` in
  `moat/link/metrics/backend/victoria/__init__.py` and
  `time.monotonic_ns()` in `moat/lib/micro/__init__.py` are *not* in the
  issue’s stated scope (~51 `time.time()` + ~14 `time.monotonic()`); leave
  them. If desired, a follow-up issue can extend `moat.util.time` with
  `time_ns`/`monotonic_ns`.

## Review checkpoint

Plan covers a new public module + API, a behavioral tweak to `times.now()`,
and touches ~26 files. Per AGENTS.md this warrants a review sub-issue blocking
moat-aqu. Created after the plan is committed.
