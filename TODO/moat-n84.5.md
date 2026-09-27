# moat-n84.5: heat package skeleton and shared infrastructure

Plan for review. HEAT.md §2 and §5 are the spec. This plan records where it
deviates from them and how the work is split into commits.

## Time (replaces `clock.py`)

There is no `clock.py` and no clock object passed to the units.

- Monotonic time and timers: `anyio.current_time()`, `anyio.sleep_until()`,
  `anyio.move_on_after()` (via `moat.util.time.loop_time()` where a loop may
  be absent). Tests fake it with trio's `MockClock` (autojump).
- Cores run on monotonic time: they get `now` (loop time) as an argument,
  never read a clock, and ask to be woken after a delay.
- Wall-clock time is only needed at the edges: persisted PID timestamps
  (converted on save and load), override expiry, and comparison with
  `MsgMeta.timestamp`. It comes from `moat.util.time.time()`. A test
  fixture patches it to `<fixed epoch> + anyio.current_time()`, so both
  clocks advance together under `MockClock`.
- Closed-loop tests of cores need neither: they are a plain loop that calls
  `core.step(inputs, now)` and `sim.step(dt)`.
- Tests against a real Link server (Scaffold) run in real time with short
  timeouts, as before.

Step 0 updates HEAT.md §2.1 (package layout), §2.2 and §5.2 accordingly.

## Steps

Each step is one commit with its tests. Modules pass `ty`.

### 0. HEAT.md: drop `clock.py`

As described above.

### 1. `config.py`, `_cfg.yaml`

- `_cfg.yaml`: package defaults, one subtree per unit plus the shared
  `service` (host name, default `heat`) and `emergency` items. Units are
  empty for now; each unit issue adds its fields.
- `HeatCfg` (shared) and a `UnitCfg` base, both subclasses of
  `moat.lib.config.base.BaseModel`.
- `unit_config(link, unit, model)`: async iterator. It merges
  `combine_dict(<Link item cfg.app.heat.<U>>, CFG.dev.heat.<U>)` with the
  Link item taking precedence, validates, and yields a fresh instance on
  every change of the Link item. An invalid update is logged and skipped.
  Deleting the item yields the defaults again.

  `BaseModel.cfg_monitor` (n84.3) watches the local `CfgStore`, not a Link
  item, so it is not used here. The package defaults are static.
- `test_config.py` (Scaffold): defaults only, partial Link item overriding
  nested keys, live update, invalid update rejected, item deleted.

### 2. `link.py`

- `Reader[T]`: wraps `d_watch(path, meta=True)`. `value`, `ts`
  (`MsgMeta.timestamp`), `fresh(now, max_age)`, `wait_value()`,
  `wait_changed()`.
- `Inputs`: a set of readers merged into one "something changed" event, plus
  `snapshot()` for the core.
- `Writer`: `d_set(..., retain=True)` with a per-path last-value cache
  (replaces KV `idem=True`).
- `Override[T]`: tri-state reader for `app.heat.override.*`. Accepts a bare
  value / `None`, or `{value, expires, reason}`. After `expires` it reads as
  `None` and fires a change. Missing fields mean "no expiry" / "no reason".
- `ServiceMonitor`: "is service X alive", from the
  `run.host.<host>.heat.<U>` announcement (present = alive).
- `test_link_helpers.py`: Reader staleness against patched wall time, Writer
  dedup, Override auto/hold/manual/off plus expiry plus missing fields,
  ServiceMonitor on Scaffold.

### 3. `state.py`

- `State`: pydantic base for per-unit state at `app.heat.<U>.state`.
- `StateStore(link, unit, model)`: `load()` (defaults if absent),
  `changed(immediate=False)`, and a saver task debounced by `save_delay`
  (default 10 s); `immediate=True` writes right away.
- `test_state.py` (Scaffold): debouncing, immediate write, defaults on first
  run, restart restores.

### 4. `pid.py`

- `PIDState` (`i`, `e`, `setpoint`, `t`) as a pydantic model that lives
  inside a unit's `State`.
- `APID`: wraps `moat.lib.pid.CPID`, keeping its contract: the input is
  the current measurement, not the error. It runs on monotonic time; `t` is
  converted to wall time when the state is saved and back when it is
  loaded. On load, a `t` older than `rebase_after` is moved to "now", so
  the first step after an outage doesn't integrate over it. Writes value and setpoint to
  the configured `log.value` / `log.setpoint` paths through a `Writer`.
- `test_pid.py`: state persisted and restored across instances, no
  integrator jump after a restart one hour later, logging.

### 5. `unit.py`

- Core protocol: `step(inputs, now) -> Step` with `outputs`, `actions`
  and `wake_in` (a delay in seconds, or `None`). `now` is monotonic.
- `Unit` base (Link adapter): loads config (step 1) and state (step 3),
  builds the readers from the config, announces the service, then loops:
  wait for an input change or until `wake_in` has passed, call
  `core.step(snapshot, anyio.current_time())`, write outputs, save
  state. A config change rebuilds the readers.
- `test_unit.py`: a trivial core on Scaffold (input change triggers a
  step, `wake_in` triggers a step, config change is applied).

## Review decisions

- Cores use monotonic time and request wake-ups as a delay.
- Publishing an event when an override expires is left to the units;
  `Override` only signals the change.
- The simulator keeps its dataclass configuration (it is not production
  code).
