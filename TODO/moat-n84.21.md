# moat-n84.21: system runner and end-to-end scenarios

The runner (`system/runner.py`, `moat dev heat run`) exists and is
tested (`test_run.py`); this issue is about the scenarios.

## What exists

- Closed-loop (cores + plant, simulated time, `sim.loop.ClosedLoop`):
  `pump_loop` (target, heat_valve, flow, pump, frost); scenarios
  cold_start/steady/deice vs. legacy metrics in `test_pump_states.py`,
  pellet handover in `test_pellet.py`, frost in `test_frost.py`,
  passthru in `test_passthru.py`.
- Legacy reference traces: cold_start, steady, deice, pellet_handover,
  day_night, frost, error_mid_run, hp_no_power, bypass.
- No Link-level end-to-end test yet. The emergency shutdown, stale-sensor
  abort, watchdog and override expiry live in the adapters, so the
  closed loop can't cover them.

## Two layers

1. **Closed loop** (`test_closed_loop.py`): every scenario that the
   cores alone decide, fast. All units' cores (incl. pellet, selector,
   errors, passthru) wired by a shared `full_loop()` (extends
   `pump_loop`), plus a "plant rules" callback for what the KV rules and
   the Solvis do in production (burner run follows `power.cmd.auto`,
   valve feedback follows its command).
2. **Link** (`test_integration.py`, `test_restart.py`): all units run
   by `run_units` (DEFAULT, plus the watchdog in its own task as in
   production), the simulator's Link adapter, on one Scaffold.
   Simulated time: trio's `MockClock` with autojump (threshold ~0.05 s,
   as `test_dev_server.py` does with Scaffold), wall clock patched to
   follow it (`patch_clock`), `SimLink(scale=1)`. Unit timings are the
   production defaults, so scenarios stay short (≤ 2 h simulated).

## Safety invariants

A checker (`tests/moat_dev_heat/invariants.py`) watches every tick
(closed loop: `ClosedLoop.watchers` + plant truth; Link: the plant
truth after each `SimLink.step`) and fails the test on:

- heat pump loaded (`hp` stage running/power > 0) while plant flow is 0
  (with the start delay allowed),
- `t_out` at or above the plant's trip temperature,
- PWM 0 while `t_out - t_in > stop.delta` for longer than a grace
  period (sensor lag),
- the pump unit writing `cmd.*` while passthru is bypassed.

The emergency scenarios where we *expect* a violation (flow unit dead)
assert it explicitly instead.

## Scenarios

| Scenario | Layer | Checks |
| --- | --- | --- |
| cold start / warm-up to `run` | both | legacy metrics (closed loop); `run` reached (Link) |
| steady cycling | closed | legacy metrics |
| de-ice | closed | legacy metrics, flow during ice |
| WP → pellet → WP handover | closed | legacy `pellet_handover`; buffer never below `t_low` minus margin |
| pellet ignition failure → fallback to WP | closed | selector fails pellet, WP runs |
| day/night switch | closed | legacy `day_night`: setpoint changes, forced day |
| error mid-run | both | closed: `errors` → selector/pump stop (legacy `error_mid_run`); Link: critical error → emergency shutdown sequence, then recovery |
| heat pump draws no power | closed | legacy `hp_no_power` |
| stale sensor | Link | pump unit aborts with emergency shutdown |
| flow unit dead during emergency | Link | documented residual risk: the shutdown times out, heat pump off; assert that, not the invariant |
| pump restart mid-run, no watchdog | Link (`test_restart.py`) | resumes from state, PIDs restored, no shutdown |
| pump killed, watchdog fires | Link (`test_restart.py`) | watchdog's shutdown, audit record |
| overrides wp / pellet / flow_temp with expiry | Link | effect, then lapse and item deleted |
| passthru while WP runs | closed (exists) | moved into the shared file / invariants |
| force start | Link | `--force-on` item starts a warm-buffer pump once, item reset |

## Steps

0. **PID clock** — done (`moat.lib.pid`; heat units and MoaT-Link
   metadata already use `moat.util.time`): on CPython it
   imports `time.monotonic` directly, so tests can't patch it; use
   `moat.util.time.monotonic` there (MicroPython keeps `ticks_ms`).
   Also `set_state(state.get("t", t or time()), …)` treats `t == 0` as
   "no time" — MockClock starts at 0; use `is None`. Check the rest of
   `moat.dev.heat` / `moat.link` paths used by the units for other
   direct clock reads while at it.

1. **Spike**: one Link scenario (warm-up to `run`) with MockClock +
   Scaffold + all units. If autojump doesn't cooperate with the
   Scaffold (spurious timeouts), fall back to real time with
   `SimLink(scale=…)` and shortened unit timings via config items;
   record the outcome here before going on.
2. Invariant checker + `full_loop()`; move the existing closed-loop
   scenarios (`test_pump_states`, `test_pellet`, `test_frost`,
   `test_passthru`) into `test_closed_loop.py` with the checker (their
   unit-specific helpers move along or into a shared module), add the
   new closed-loop ones.
3. `test_integration.py`: the Link scenarios above.
4. `test_restart.py`.
5. HEAT.md §5 (time handling for Link tests, as implemented; scenario
   table), close.

Review: MockClock approved (step 1 confirms it); existing closed-loop
scenarios move into `test_closed_loop.py`.
