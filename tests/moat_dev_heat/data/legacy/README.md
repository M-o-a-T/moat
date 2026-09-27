# Legacy reference traces

Closed-loop runs of the legacy controller (`moat/dev/heat/solvis.py`,
class `Data`) against the plant simulator (`moat.dev.heat.sim`). The new
units are compared against these (HEAT.md §5.1). Produced by
`tests/moat_dev_heat/legacy.py` and checked by `test_legacy.py`.

Regenerate with

    python3 -m tests.moat_dev_heat.legacy [SCENARIO…]

or `MOAT_HEAT_REFRESH=1 pytest tests/moat_dev_heat/test_legacy.py`.

Nothing touches a real MoaT-KV server or MQTT broker: `solvis` is
imported with a dummy `/etc/moat/moat.cfg`, its `open_client` is replaced
by a function that raises, and all KV traffic goes through an in-memory
fake.

## File format

One JSON object per line. Line 1 is the header: scenario name, `doc`,
and `events` — `[t, "run", state]` for every controller state change,
`[t, <input>, value]` for scripted inputs, `[t, "exception", text]` if
the controller died. Every following line is a sample (every 60 s of
simulated time, `t` in seconds from the scenario start):

| Key | Meaning |
| --- | --- |
| `run` | legacy `Run` state |
| `hc` | last heating-circuit decision (`log_hc` number) |
| `power`, `mode` | heat-pump commands `cmd.power`, `cmd.mode.path` |
| `pwm` | circulation-pump output `output.flow.path` |
| `heat_mode` | heating valve `setting.heat.mode.path` (3 on, 5 standby) |
| `curve` | flow setpoint `adj.curve.setting` |
| `p_wanted`, `p_load`, `p_temp` | pellet commands |
| `t_in` … `m_switch` | true plant values (no sensor noise) |
| `hp` | simulated heat-pump stage |

## Scenarios

| Name | What happens |
| --- | --- |
| `cold_start` | cold buffer, cold day: start-up, warm-up, de-ice, cycling |
| `steady` | mild weather, warm buffer: normal cycling |
| `deice` | cold humid air: repeated de-icing while running |
| `pellet_handover` | frost then thaw: pellets take over, later hand back |
| `day_night` | 18:00 to 10:00: night setback at 21:30, forced day mode 04:00–06:00 |
| `error_mid_run` | heat-pump error at 2 h, cleared at 3 h |
| `hp_no_power` | heat pump stops drawing power at 1 h, error on `:1` |
| `bypass` | manual bypass from 1 h to 2 h |

## Harness assumptions

- Configuration: the legacy `CFG` literal overlaid with the production
  file (`../solvis.yml`, a copy of `/tmp/moat/solvis.yml`).
- The Solvis echoes our flow setpoint (`heat.s.heat.temp.cmd`) as its
  heating target `heat.s.heat.temp` (`c_heat`).
- The burner command `cmd.pellet.run` follows `cmd.pellet.wanted`, as
  the production KV rule does.
- Plant parameters are the simulator defaults, not measurements, so
  absolute numbers (run lengths, temperatures) are only indicative.
  State sequences and decision rules are what matters.
- A controller exception ends the trace. In production, `run`'s
  `finally` then calls `Data.off()` and systemd restarts the process;
  the harness does not emulate that.

## Known quirks of the legacy controller

New units should either match these or deviate deliberately.

1. **Selector cadence.** `run_temp_thresh` decides only on every 10th
   update of *any* input, so its reaction time depends on unrelated
   sensor rates (HEAT.md §1).
2. **PID cadence and clock.** All PIDs tick on any input change and read
   `time.monotonic()` themselves; no timestamp is passed.
3. **Heating valve flaps on every heat-pump stop.** Entering `down`
   sets `heat_off`, which puts the heating circuit into standby (5); it
   comes back (3) after `setting.heat.mode.delay` once in `off`. Visible
   in every scenario as a one-minute `heat_mode` 5 blip per cycle.
4. **Curve setpoint has no hysteresis.** `int(flow_temp + 0.8)` follows
   the outside temperature directly and toggles by 1 °C with sensor
   noise (`day_night`).
5. **No power while starting is only caught by the start timeout.**
   `wait_power` has no no-power rule; after `lim.times.start` the
   controller raises `TimeoutError` and exits (`hp_no_power`). In `run`,
   the 30 s no-power rule turns it off, and it restarts at once if the
   buffer is still cold.
6. **Ignored errors.** Code 30055 and path `:1` never block the heat pump
   (`hp_no_power`); any other error stops it via `down` (`error_mid_run`).
7. **De-ice exit waits for the start delay.** `ice` → `wait_time`, so
   after every de-ice cycle the heat pump waits `misc.start.delay`
   before restarting.
8. **Bypass.** While bypassed, `state.run` keeps its previous value; on
   leaving bypass the controller is forced into `down` (`bypass`).
9. **Heat pump and pellets run together.** While the burner is on, the
   heat pump keeps being started when the buffer is cold; it only stops
   early when the burner is hot enough (`OFF 3`/`OFF 6`), and the burner
   is driven at full load whenever the heat pump runs (from the code;
   `pellet_handover` currently ends before this shows, see below).
10. **Several state changes per tick.** A transition `continue`s without
    waiting, so e.g. `down` → `off` → `wait_time` can happen within one
    input update.
11. **Run state is written to `sensor.pump.state`**, the heat pump's own
    state path (HEAT.md §1).

## Problems found while building the harness

- `solvis.py` no longer imported: `t_iter` moved from `moat.util` to
  `moat.util.times` (fixed).
- Open question (moat-vou): `CPID.__call__(measurement)` passes
  `setpoint - measurement` to `PID.__call__`, which calls the overridden
  `CPID.integrate` with it, so the setpoint is subtracted a second time.
  With the production `flow` gains, setpoint 15 and a measured 28,
  `pid(28)` returns 0.95 while `pid.sum(pid.integrate(28))` returns 0.25.
  The legacy code uses the first form for the flow and pump PWM, so in
  these traces the circulation pump runs at maximum whenever it is under
  flow or temperature control. At −6 °C that keeps `t_out - t_in` below
  `misc.start.delta`, and `pellet_handover` ends with the start timeout.
  The traces are recorded with `moat.lib.pid` as it is.

## Reproducibility

The harness runs trio with deterministic scheduling (seeded, as
`tests/__init__.py` does under `PYTHONHASHSEED`), wakes tasks waiting
on the same `trio.Event` in name order, and advances the mock clock by
hand, so a scenario gives the same trace every time.
