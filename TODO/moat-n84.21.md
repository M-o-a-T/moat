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

1. **Spike** — done (`test_integration.py::test_warmup`). Outcome:
   - MockClock + Scaffold works, with two adjustments to the wall clock
     (`WallClock`): it must strictly advance (MoaT-Link drops an update
     whose timestamp isn't newer, and with a mock clock two updates can
     share an instant), and it must start at the real time (the Link
     server's connection-rate check keeps state across the tests in a
     process and fails when time goes backwards). Autojump threshold
     5 ms (50 ms was 4× slower); stable in the parallel suite.
   - Speed: about 24× real time once running (30 simulated minutes in
     76 s), plus ~6 s start-up. Logging doesn't matter.
   - Found: the pump's stale-sensor abort fires after 900 s of a steady
     `r_flow` — the simulator quantises flow without noise, and values
     are published on change only, so "unchanged" ≠ "stale" (see
     questions).

   Original text: one Link scenario (warm-up to `run`) with MockClock +
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

Review: Link scenarios stay ≤ 15 simulated minutes, marked `slow`; long
ones are closed-loop only. Stale sensors: (d), below.

## Step 1b: refreshing steady values (review answer d)

Values are published on change, so a steady reading looks like a dead
sensor. Fix: the poller re-publishes an unchanged value regularly, and
the heat units treat *every* received update as fresh: no value or
timestamp comparisons.

1. `moat.link`: `LinkSender.set(…, idem=…)` takes a bool or a number.
   A number N: an equal stored value is only left alone if it is younger
   than N seconds (by its metadata timestamp); else it is written again.
   Test, docstring.
2. `moat.modbus` (`dev/link.py`, `Register.to_link`): send with
   `self._link.set(dest, val, idem=N, …)` instead of the local
   `last_sent_value` comparison, and also wake up every N/2 s without a
   change (the slot only notifies on a changed value), so a steady value
   is re-sent at most 1.5 N after the last write. Register option `idem`
   (number; default N = 120 s, so the flow unit's 300 s is met). Test
   with a fake device and Scaffold; document in `dev-poll.md`.
3. `moat.dev.heat`:
   - `Reader` records when it last received an update (`t_upd`, on
     `loop_time()`), for every message, equal or not. The first value is
     primed from its age (`time() - timestamp`), capped at 9/10 of the
     reader's `max_age` (new optional argument), so at least 1/10 of the
     timeout remains: for the pump's 900 s, a value older than 810 s
     gets 90 s.
   - `Unit` adds these to the snapshot (`inputs["_upd"]`: name →
     `t_upd`); `ClosedLoop` too (and patches `monotonic` to its `now`,
     also while adding cores).
   - Pump adapter: stale = no update for `stale` (900 s); its readers
     for `stale_sensors` get `max_age=stale`.
   - Flow core: a sensor is stale after `max_age` (300 s, unchanged)
     without an update; readers get `max_age`. Without `_upd` (direct
     core tests) it falls back to value changes, as now.
   - Check the other units for value-change-based staleness (`target`'s
     `t_ext` comes from the aggregation job, not the poller).
   - Simulator publishers (`SimLink`, `ClosedLoop.publish_sensors`)
     re-send a steady value every 120 s, as the poller does.
4. Then `test_warmup` runs 30 simulated minutes without a stale abort.
