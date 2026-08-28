# Refactoring the `moat.dev.heat` Solvis controller

`moat/dev/heat/solvis.py` currently contains a single 2270-line module that
implements the whole heat-supply controller (heat-pump + pellet boiler +
heating curve + flow control) as one big `Data` class plus a yaml config
literal. This document plans the split into independent, testable units
and the migration from MoaT-KV to MoaT-Link.

The goal is a clean rewrite. Incremental switch-over, on-disk-state
compatibility, or KV/Link parallel operation are **non-goals**. We replace
the configuration file with structured data items stored in MoaT-Link.

The result replaces `moat/dev/heat/solvis.py` with a set of small
unit modules directly under `moat.dev.heat`. The old `solvis.py` is
removed when the new code lands.

## 1. What the existing code does

A breakdown of the current monolith. The numbers in parentheses are the
methods of the existing `Data` class.

| Concern | Current location | Notes |
| --- | --- | --- |
| State machine for the heat-exchanger (heat pump) | `run_pump` (state machine + entry/exit actions) | `Run` enum: off → wait_time → wait_flow → flow → wait_power → temp → run → down, plus `ice`. |
| Heat-pump setpoint computation | `run_pump`, mid-function | Mixes hot-water and heating buffer targets, max/limit math, “low" scaled average. |
| Heat-pump load PIDs (`load`, `buffer`, `limit`, `pump`) | `run_pump` | Drive heat-exchanger load and outflow temperature. |
| Heating-valve / day-mode on/off | `run_pump`, end | Looks at `tb_heat`, `c_heat`, switch state, then toggles `setting.heat.mode.path`. |
| Pump (water-pump) PWM control | `handle_flow` + the `flow` PID in `run_pump` | Computes a PWM duty from desired flow rate and temperature. |
| Pellet burner control | `run_set_pellet` | Reads pellet state machine, runs `p_load` / `p_buffer` PIDs, writes load goal. |
| Selecting WP vs. pellet | `run_temp_thresh` | Based on outside air temp current+forecast, current state, and buffer levels. |
| Heating curve (target temperature) | `run_set_heat` | Outside-air temp + day/night + forced override → desired flow temperature. |
| Error monitor | `err_mon` | Watches `sensor.error`, populates `m_errors`, vetoes WP run. |
| Emergency shutdown | `off` | Load → 0, flow until ΔT < `misc.stop.delta`, then PWM → 0. |
| Config + persistent state | `CFG` literal + `/tmp/solvis.state` + optional file watcher (`reload_cfg`) + `saver/save` | YAML; one big tree. |
| Recording / replay | `record=`, `run_rec`, `run_fake`, `fake_cl` | For offline analysis. |
| KV plumbing | `_kv`, `cl_set`, `has`, `wait`, `all_done`, `trigger` | Translates KV streams to attributes on `self`. |
| Software PWM daemon | `pwm` / `_run_pwm` (top-level Click cmd) | RPi.GPIO based; not part of the controller loop. |
| Modbus monitor babysitter | `run_solvis_mon` | Restarts `moat modbus dev poll` on certain errors. |

The control loops all share state on a single `Data` instance, with attrs
such as `self.t_adj`, `self.heat_dest`, `self.pellet_on`, `self.wp_on`,
`self.state.t_pellet_on`, the `self.pid.*` PIDs, and many KV-fed sensor
attrs (`t_in`, `t_out`, `tb_*`, `m_*`, `r_flow`, …).

## 2. Target architecture

### 2.1 Modules

Units are independent and individually restartable. Each one runs as a
standalone process (`moat dev heat <unit>`); a convenience
`moat dev heat run` starts all of them in one task group on one
host. Communication between units is always through moat-link.

The `solvis` subpath of the old code is dropped: the new unit modules
live directly under `moat/dev/heat/`. A `system` subpackage holds
tasks that orchestrate multiple units or operate on the whole system
(combined runner, migration, replay).

New package layout:

```
moat/dev/heat/
    __init__.py
    _cfg.yaml         # package-default config (loaded via moat.lib.config)
    _main.py          # click subcommands for every unit + system tasks
    kwb.py            # existing KWB modbus helper (unchanged)
    config.py         # pydantic config models (see §2.4)
    link.py           # Link helpers: Reader, Writer, Heartbeat, Override
    emergency.py      # shared emergency_shutdown() helper (see §2.5)
    pid.py            # APID (PID + async logging) reused from old file
    state.py          # per-unit persistent state, stored under each unit's path
    pump.py           # heat-exchanger state machine + load control
    flow.py           # water-pump PWM controller
    pellet.py         # pellet burner load controller
    selector.py       # WP vs pellet decision
    target.py         # heating curve / temperature goal + heat-valve
    errors.py         # error aggregator (publishes only; see §2.5)
    watchdog.py       # external watchdog (optional, see §2.5)
    system/
        __init__.py
        runner.py     # `moat dev heat run`: start all units in one task group
        migrate.py    # one-shot KV → Link data migration script
        replay.py     # recording playback (dev/test tool)
```

Each unit is a small module with:
- one `async def run(link, cfg) -> NoReturn` entry point taking a
  `moat.link.client.LinkSender` and its typed pydantic config,
- no global state, no shared in-process objects with other units.

The TUI/CLI: `moat dev heat run` (all units), `… pump`, `… flow`,
`… pellet`, `… selector`, `… target`, `… errors`, `… watchdog`,
plus `… off`, `… curve`, `… migrate`. Each unit subcommand is
implemented as a tiny wrapper that calls the unit's `run()`.

### 2.2 Inter-unit communication: moat-link only

Every cross-unit value flows through moat-link. Internal in-process
coordination between units does not exist: anything one unit needs to
know from another, it `d_watch`es. Anything it wants other units to
see, it `d_set`s with `retain=True`.

This makes restart, replacement, and override trivial: a restarting
unit gets the last retained value of every input on first message; a
maintenance override is just an extra writer to a published path; and
the units are isolated processes that can run on different hosts.

#### Path layout

Three namespaces, by retention semantics:

- `cfg.app.heat.<U>` — retained, the unit's typed config. The operator
  (or the migration script) writes this; the unit reads it at startup
  and optionally `d_watch`es it for live reload.
- `app.heat.<U>.*` — retained operational data: published outputs,
  persistent state, override, peer-facing requests. Survives restart.
- `run.app.heat.<U>.*` — non-retained, ephemeral runtime topics:
  keepalive heartbeats and one-shot operator commands.

For each unit `U` (one of `pump`, `flow`, `pellet`, `selector`,
`target`, `errors`, `watchdog`):

| Path | Direction | Retained | Contents |
| --- | --- | --- | --- |
| `cfg.app.heat.<U>.<app>`       | unit reads      | yes | typed config (see §2.4) |
| `app.heat.<U>.out`             | unit writes     | yes | the unit's primary published value (see per-unit specs) |
| `app.heat.<U>.state`           | unit writes     | yes | persistent state (see §2.3) |
| `app.heat.<U>.override`        | operator writes | yes | manual override (see §2.6) |
| `app.heat.<U>.flow.request`    | pump/pellet/emergency write | yes | the flow unit's input request |
| `run.app.heat.<U>.alive`       | unit writes     | **no** | heartbeat: `{ts, pid, build}`; published every `cfg.app.heat.<U>.alive_interval` seconds |
| `run.app.heat.<U>.cmd`         | operator writes | **no** | one-shot commands (`reload`, `stop`, …) |

The service-announce path is `run.host.<hostname>.heat.<U>` (this is
moat-link's standard, supplied by `moat.link.announce.announcing`).

Sensor and physical-output paths (`heat.s.pump.temp.in`, the PWM
output, the load setpoint to the heat exchanger, etc.) keep their
existing locations — they're not owned by us. Their mapping into the
unit's view is part of each unit's `cfg.app.heat.<U>`.

#### Read pattern

A unit that depends on another unit's output (e.g. `pump` depends on
`target.out` for setpoints and on `selector.out` for whether to run)
uses one `d_watch(…, state=None, retain=True)` per input. The Reader
helper in `link.py` exposes each input as a small object:

```
class Reader[T]:
    value: T | None         # last seen, or None until first message
    ts: float | None        # MsgMeta.timestamp of last update
    fresh(max_age: float) -> bool
    async def wait_value() -> T   # wait until first message received
    async def wait_changed() -> T # wait until next change
```

The unit's main loop merges these readers (the existing
`anyio.create_memory_object_stream` pattern) into a single "any input
changed" stream.

#### Staleness handling

Each Reader has a configured `max_age`. The unit decides what to do
when an input is stale. The conservative defaults:

- `pump`: if any of its sensor inputs are stale > 30 s, transition to
  `down` (safe-shutdown via the existing state machine; the unit
  itself contains the recovery logic, see §2.5).
- `flow`: if `r_flow` or `t_out` stale > 10 s, freeze PWM at last
  value for `freeze` seconds then drop to a configured `safe_pwm` to
  keep the pump turning, never to zero. Never wait for sensors to
  recover before exiting `freeze`; treat the timeout as terminal and
  fall through to `safe_pwm`.
- `pellet`: if its inputs are stale, hold last load output, then drop
  to 0 after `freeze`.
- `selector`: if any sensor is stale, latch the last decision; do not
  flip on stale data.
- `target`: if outside-air is stale, hold last `flow_temp`. After
  `freeze` use the curve's `dest` value alone.
- `errors`: stale error feed itself is reported as a synthetic error
  on its own `out` path so that consumers see it.

All `max_age` / `freeze` / `safe_pwm` values are config knobs.

#### Write pattern

Units use `link.d_set(path, value, retain=True)` for state and primary
outputs, and `link.send(path, value, retain=False)` for transient
events ("override accepted", "de-ice started"). The Writer helper
debounces no-op publishes (last-value-cache, `idem=True` equivalent
behaviour).

#### Heartbeat / watchdog

Every unit publishes to `run.app.heat.<U>.alive` with a timestamp
roughly once a second (configurable). This is a **non-retained**
topic by design: a restarted unit must publish a fresh heartbeat to
be considered alive; a stale value can never linger. Consumers of a
unit's output use `Reader.fresh(max_age)` on the corresponding
`alive` subscription to decide whether the unit is up.

This is also what allows an external supervisor to restart a unit,
and what allows the operator to see at a glance which unit is healthy
in a TUI / dashboard.

For the pump unit specifically, a small **external** watchdog process
(`moat dev heat watchdog`, optional) can be deployed: if
`run.app.heat.pump.alive` is stale beyond a threshold *and* the last
`app.heat.pump.out` says the pump is in `run`, the watchdog runs the
emergency-shutdown procedure (§2.5).

### 2.3 Persistent state

Each unit owns its own state under `app.heat.<U>.state`. There is no
shared cross-unit state object. A `State` base class in `state.py`
provides:

- typed `pydantic` model fields (subclassing
  `moat.lib.config.base.BaseModel`),
- `load(link)` — read the retained item at startup, with sensible
  defaults if absent (first run),
- `save(link)` — publish; debounced by a configurable interval (default
  10 s) plus an immediate-write flag for critical changes (state
  transitions in pump),
- `touch()` — mark dirty.

PIDs read/write their slot via the existing `APID` mechanism, but the
state dict lives inside the owning unit's `State` (e.g.
`PumpState.pids.load`, `PelletState.pids.p_load`).

On restart, a unit calls `state.load()` before entering its main
loop, so a clean restart resumes the previous PID integrators, last
run mode, etc.

### 2.4 Configuration in moat-link

Configuration moves from the embedded `CFG` yaml literal to **one
moat-link data item per functional unit**, all under the `cfg.app.heat`
subtree:

| Path | Schema |
| --- | --- |
| `cfg.app.heat.pump`     | heat-exchanger limits, PIDs (`load`,`buffer`,`limit`,`pump`), timings, de-ice, stop conditions, paths to sensors and to load/mode outputs, paths to subscribe for `target` and `selector`. |
| `cfg.app.heat.flow`     | water-pump PID, PWM bounds, GPIO/output path, staleness behaviour. |
| `cfg.app.heat.pellet`   | pellet PIDs (`p_load`,`p_buffer`), `lim.pellet.*`, startup-patch list, paths for state/load/wanted, `target`+`selector` input paths. |
| `cfg.app.heat.selector` | thresholds for switching WP/pellet (`misc.pellet.*`, hysteresis), sensor paths, `target` input path. |
| `cfg.app.heat.target`   | heating curve, day/night schedule, force-override paths, outside-air sensor path, setting-output path. |
| `cfg.app.heat.errors`   | error sensor path, aggregation rules, list of error codes to ignore. |
| `cfg.app.heat.emergency`| shared by pump/watchdog/CLI; see §2.5. |
| `cfg.app.heat.watchdog` | watchdog tunables; see §2.5. |

Defaults for these items ship in `moat/dev/heat/_cfg.yaml` and are
loaded by `moat.lib.config` (each unit calls `register(__name__)` in
its module so its defaults are present in `CFG`). The operator's
moat-link store overrides the defaults; the migration script (§4.1)
populates them from the existing yaml.

#### Pydantic-typed config

Each unit defines a config class in `moat/dev/heat/config.py` (or in
the unit's own module) by subclassing
`moat.lib.config.base.BaseModel`. That base already provides
`extra="allow"`, `validate_assignment=True`, `strict=True`, plus an
`add_field_` for dynamic extension.

Example sketch:

```python
from moat.lib.config.base import BaseModel
from moat.lib.path import Path

class PumpPidCfg(BaseModel):
    p: float
    i: float
    d: float = 0.0
    tf: float = 0.0
    min: float
    max: float
    state: str  # state-slot key

class PumpCfg(BaseModel):
    sensor_in:    Path
    sensor_out:   Path
    sensor_flow:  Path
    load_path:    Path
    mode_path:    Path
    target_input: Path  # app.heat.target.out
    selector_input: Path
    pids: dict[str, PumpPidCfg]   # load, buffer, limit, pump
    times: PumpTimesCfg
    …
```

A unit reads its config as:
```python
from moat.lib.config import CFG

cfg = PumpCfg.model_validate(CFG.app.heat.pump)
```
or, for live reload, by `d_watch`ing `cfg.app.heat.pump` and
`model_validate`-ing each new value.

#### Extensions to `moat.lib.config.base`

The rudimentary `BaseModel` there needs a few additions for our use,
which land in a separate commit *before* the heat refactor (so other
modules can benefit too):

- **`moat.lib.path.Path` support.** A custom pydantic validator that
  accepts both `Path` instances and strings (parsed via `P(…)`) and
  serialises back to `Path`. The yaml-loaded form is already a
  `Path` thanks to the `!P` tag, so this is mostly for round-trip
  through moat-link's codec.
- **`attrdict` input compatibility.** `model_validate(attrdict(…))`
  should work without an explicit `model_validate_json` step.
  Pydantic's default coercion handles dict-likes, but we double-check
  with a regression test.
- **A `from_cfg(path)` classmethod** on `BaseModel` that reads the
  subtree from the active `CFG` and validates. Optional convenience.
- **`monitor()` integration.** A helper that ties
  `moat.lib.config.monitor` to model re-validation, yielding a fresh
  typed instance on each change. Used by `target` for live curve
  reload.

These extensions are listed in HEAT.md as prerequisites; they get
their own beads issue with label `common`.

There is intentionally no "global bus" config: each unit's config
carries all the paths it needs, so units truly are independent. The
small amount of duplication (e.g. the `app.heat.target.out` path
appears in `pump`, `pellet`, and `selector` configs as their input)
is worth the isolation; the migration script and a `… heat check`
command keep them in sync.

### 2.5 Emergency shutdown and recovery

The water pump cannot just be stopped: while the heat exchanger is
still producing heat, removing circulation would overheat it. So
emergency shutdown is a **sequenced procedure**, not a single action:
first stop the heat-exchanger controller, then keep circulating until
the residual heat has dissipated, then stop the water pump.

#### Service-supplant model

The `pump` unit announces itself via `moat.link.announce.announcing`
at a well-known service path (the unit's name under
`run.host.<hostname>`). Any other process that calls
`announcing(…, force=True)` against that path takes over: the running
pump unit's announcement monitor raises `ServiceSupplanted` and its
`run()` exits cleanly. This is the mechanism used by the operator's
emergency-off command and by the watchdog. It works even when the
pump unit is otherwise responsive (the operator wants control) and
when it is silently stuck (the supplant still proceeds; the
supplanted task's exit doesn't block the new owner).

#### The procedure

A shared helper `emergency.emergency_shutdown(link, cfg, *,
from_pump: bool = False)` implements the sequence. It is called from
three places:

- the pump unit's own `finally` block, with `from_pump=True` (the
  pump already owns the service);
- the watchdog, with `from_pump=False`;
- the `moat dev heat off` CLI command, with `from_pump=False`.

The procedure, in order:

1. **Take over the pump service** (only when `from_pump=False`):
   enter an `async with announcing(link, name=…pump…, force=True)`
   block. Any running pump unit is supplanted and exits via
   `ServiceSupplanted`. If no pump unit was running, the announce is
   a no-op except that it advertises that emergency shutdown owns
   the service.

2. **Stop the heat exchanger.** Write `0` to the heat-pump load path
   and the configured "off" value to the mode path. These are the
   same paths the pump unit normally writes. There's no race because
   we now own the service (`from_pump=True`) or have just taken it
   over.

3. **Keep the water pump running.** Publish to
   `app.heat.flow.request` a request with
   `{mode: "drain", rate: cfg.emergency.flow_rate}`. The `flow`
   unit serves this just like any other request; its loop continues
   unchanged. We rely on the `flow` unit being alive. (If it isn't,
   the Solvis controller's own hardware safety limits are the next
   line of defence; see the risks section.)

4. **Wait for cool-down.** Concurrently watch `sensor.pump.in`,
   `sensor.pump.out`, and an `anyio.move_on_after(cfg.emergency.timeout)`
   (default **120 s**). Exit the wait when **either** of these is true:
   - the timeout elapses, **or**
   - both sensors have a fresh reading (younger than
     `cfg.emergency.max_sensor_age`, default 30 s) **and**
     `t_out - t_in < cfg.emergency.stop_delta` (default 3 °C).

   We intentionally do not wait indefinitely for the temperature
   condition. The sensors may be the reason we're shutting down in
   the first place; their values may be stuck or absent. The wall-
   clock timeout is the unconditional safety net.

5. **Stop the water pump.** Publish
   `{mode: "off"}` to `app.heat.flow.request`. The `flow`
   unit drops PWM to 0.

6. **Release the service** (only when `from_pump=False`): exit the
   `announcing` block. The pump service is now unowned; the operator
   may restart the pump unit when ready.

The whole sequence runs inside an `anyio.move_on_after` of
`cfg.emergency.total_timeout` (default 180 s = 120 s + 60 s headroom)
as an outer hard limit, so a misbehaving step (e.g. a hung
`d_set`) cannot wedge the procedure forever.

#### When the pump unit triggers it itself

The pump unit's normal state machine handles routine shutdown via its
`down` → `off` transitions. The emergency helper is invoked
*additionally* in three cases inside the pump unit:

- `errors.out` becomes non-empty (the heat exchanger reports a fault),
- a critical sensor goes stale beyond `max_age`,
- a non-`BaseException` escapes the main loop (caught in the outer
  `try`).

In all three cases the unit calls `emergency_shutdown(link, cfg,
from_pump=True)` from its `finally` block, inside an
`anyio.move_on_after(cfg.emergency.total_timeout, shield=True)`. After
that returns, the original exception (if any) is re-raised so the
process exits; `BaseException` (including
`anyio.get_cancelled_exc_class()`) always propagates per project
rules, but only after the shielded shutdown finishes.

#### Watchdog

The watchdog (`watchdog.py`, optional) runs as a separate
process and exists to handle the case where the pump unit cannot
run its own `finally` — hard kill, kernel OOM, host crash. It:

- subscribes to `run.app.heat.pump.alive` and `…pump.out`,
- if `alive.ts` is older than `cfg.watchdog.max_age` (default 15 s)
  **and** the last `out.run` indicates the pump was in an active
  state (anything except `off` and `down`),
- calls `emergency_shutdown(link, cfg, from_pump=False)`.

The watchdog itself never restarts the pump unit; that's an operator
or systemd concern. It publishes its actions to
`app.heat.watchdog.out` for auditing.

#### Operator command

`moat dev heat off` is a thin wrapper around
`emergency_shutdown(link, cfg, from_pump=False)`. It exits when the
sequence completes (or when the total-timeout safety net fires).
Useful for maintenance: any running pump unit is supplanted, the
system is brought to a safe state, and the operator can then start
repair work.

#### Emergency config

A new `cfg.app.heat.emergency` item carries the shared
tunables:
```
flow_rate:        12          # l/min while draining
timeout:          120         # s, max cool-down wait
stop_delta:       3.0         # °C, t_out - t_in threshold
max_sensor_age:   30          # s, ignore sensor older than this
total_timeout:    180         # s, hard overall limit
load_path:        !P heat.s.pump.cmd.power
mode_path:        !P heat.s.pump.cmd.mode
mode_off_value:   0
service:          !P heat.pump  # passed to announcing()
```
The pump, watchdog, and CLI all read this single item (in addition to
their own config), so the procedure is consistent across all three
entry points.

### 2.6 Override and maintenance mode

Every unit reads its `…<U>.override` path. The override item is a
small dict:

```
{ mode: "auto" | "hold" | "manual" | "off",
  value: <unit-specific>,  # required when mode != "auto"
  expires: <epoch seconds> | null,
  reason: <string> }
```

Semantics, common to all units:

- `auto` (or item absent): normal operation.
- `hold`: freeze the unit's current output; PIDs keep integrating but
  the published `out` is held constant. Used to inspect the system.
- `manual`: publish `value` as the unit's output, ignoring inputs.
  PIDs are forced via `move_to(value)` so resumption is bumpless.
- `off`: equivalent to `manual` with the unit's safe-off value
  (for `pump`: trigger `down`; for `flow`: `safe_pwm`; for `pellet`:
  load 0; for `target`: `curve.dest`).

If `expires` is set and reached, the unit reverts to `auto` and
publishes an event saying so. This prevents a forgotten manual
override from running indefinitely.

For maintenance, the operator typically writes
`{mode: "off", expires: now()+1800, reason: "replacing flow sensor"}`
to `app.heat.pump.override`. The pump unit runs `down` and
stays in `off` until 30 minutes elapse or the override is cleared.

## 3. Unit specifications

For each unit: what moat-link paths it watches, what it publishes,
and a sketch of its main loop. Sensor / command path names are
placeholders that match the current production config—the actual
paths come from each unit's config item.

Notation:
- **Watches**: paths the unit `d_watch`es; each becomes a `Reader`.
- **Publishes**: paths the unit `d_set`s with `retain=True`.
- **State**: persistent state shape under `app.heat.<U>.state`.
- **Override `value`**: what `app.heat.<U>.override.value` means for
  this unit.

All units additionally:
- watch their own `cfg.app.heat.<U>` (load at startup; `target`
  also reloads on change),
- watch their own `app.heat.<U>.override`,
- publish their own `run.app.heat.<U>.alive` heartbeat,
- publish their own `app.heat.<U>.state`.

### 3.1 `target.py` — heating curve

Computes the desired flow temperature based on outside air and
day/night schedule. Also drives the heating-valve on/off (the tail of
the current `run_pump` is folded in here, since it belongs to the
heating-distribution side; see §7).

- **Watches**:
  - `cfg.sensor.temp.current` — outside air,
  - `cfg.setting.heat.mode.force.day.cmd`, `…night.cmd` — forced
    overrides,
  - `cfg.sensor.buffer.heat` — buffer-heat temperature (for the
    heating-valve threshold),
  - own config (live reload).
- **Publishes**:
  - `app.heat.target.out` = `{flow_temp, day_active,
    t_ext_avg, heat_valve}`,
  - `cfg.setting.heat.day` — the Solvis-facing setpoint (legacy path,
    kept for compatibility with the Solvis controller),
  - `cfg.setting.heat.mode.path` — heat-valve on/off (when the unit
    decides to engage the heat).
- **State**: `{locks: {day,night}, last_flow_temp, last_heat_valve_ts}`.
- **Override `value`**: `{flow_temp: float, day_active: bool,
  heat_valve: bool}`; any subset.

Logic is a straight port of `run_set_heat` and `vt()`. The unit ticks
on outside-air updates, on schedule transitions (`anyio.sleep` until
next boundary), and on force-cmd changes.

### 3.2 `flow.py` — water-pump PWM

Owns the `flow` PID and the PWM output. `pump` and `pellet` do not
write PWM; they request flow by publishing to a request path that
`flow` reads.

- **Watches**:
  - `cfg.sensor.pump.flow` — `r_flow`,
  - `cfg.sensor.pump.out` — `t_out`,
  - `app.heat.flow.request` — the request from the pump/pellet
    units: `{rate: float|null, mode: "normal"|"de_ice"|"idle"|"off",
    pwm_override: float|null}`.
- **Publishes**:
  - the PWM output to the configured target (GPIO via `_run_pwm`, or
    a moat-link path that the GPIO daemon reads),
  - `app.heat.flow.out` = `{pwm, mode, stable, last_request_ts}`.
- **State**: PID integrator (`state` slot of the `flow` APID).
- **Override `value`**: `{pwm: float}` to force a specific duty cycle.

Loop:
1. Wait for sensors + request retained.
2. On each input change:
   - if request mode is `off`: PWM 0;
   - else compute `l_flow = pid.flow(r_flow)` and
     `l_temp = pid.pump(t_out)` (current `handle_flow` math);
   - clamp with mode-specific minimum (`de_ice.min` in `de_ice`);
   - publish PWM and `out`.
3. If request stale > `freeze`: drop to `safe_pwm`.

### 3.3 `pump.py` — heat-exchanger state machine

Pure heat-pump controller. No pellet logic, no heating-valve logic,
no PWM writes. It only drives the load command and requests flow.

- **Watches**:
  - sensors: `cfg.sensor.pump.{in,out,flow,ice}`,
    `cfg.sensor.buffer.{top,heat,mid,low}`, `cfg.sensor.power`,
    `cfg.misc.switch.state`,
  - commands: `cfg.cmd.wp` (main switch), `cfg.cmd.bypass.*`,
  - inputs from peer units:
    - `app.heat.target.out`,
    - `app.heat.selector.out`,
    - `app.heat.pellet.out`,
    - `app.heat.errors.out`.
- **Publishes**:
  - load command to `cfg.cmd.power` + `cfg.cmd.mode.path`,
  - flow request to `app.heat.flow.request`,
  - `app.heat.pump.out` = `{run: Run, active: bool, l_load,
    l_limit, l_buf, l_pump, t_cur, scaled_low}`.
- **State**: `{run: int, t_change, t_load, t_run, scaled_low,
  load_last, avg_heat, avg_heat_t, pids: {load,buffer,limit,pump}}`.
- **Override `value`**: `{run: "off"|"down"|"hold", load: float|null}`.

The state machine is the existing `Run` enum. The transition table
currently buried in `run_pump`'s if/elif chain is extracted into a
pure function `next_state(orun, requested, sensors, signals,
errors) -> Run` with an explicit table, both for clarity and for
testing. Entry actions for each state become small methods
(`enter_off`, `enter_wait_flow`, `enter_run`, `enter_down`, …); the
per-tick logic of each state likewise (`tick_flow`, `tick_run`, …).

Safe-shutdown lives partly here and partly in `emergency.py`. The
unit's normal `down`/`off` transitions handle the routine path
(operator override `off`, selector saying "stop"). For *abnormal*
shutdown (error signal, stale sensors, uncaught exception) the
unit's outer `try/finally` invokes
`emergency.emergency_shutdown(link, cfg, from_pump=True)`; see §2.5
for the full sequence.

The pump unit registers itself via `announcing(…, force=False)` at
the service path defined in `cfg.app.heat.emergency.service`.
If another process supplants it (operator `heat off`, watchdog),
the announcement monitor raises `ServiceSupplanted`; the unit treats
this like any other clean exit (state is already retained) and lets
the new owner finish the emergency procedure.

### 3.4 `pellet.py` — pellet burner controller

Owns the `p_load`, `p_buffer` PIDs. Reads pellet state, decides
whether to push load to the pellet burner.

- **Watches**:
  - sensors: `cfg.sensor.pellet.state`, `cfg.sensor.buffer.*`,
    `cfg.sensor.temp.pellet`,
  - commands: `cfg.cmd.pellet.force`,
  - inputs from peers:
    - `app.heat.target.out`,
    - `app.heat.selector.out`,
    - `app.heat.pump.out` (for `wp_on`).
- **Publishes**:
  - `cfg.cmd.pellet.load`, `cfg.cmd.pellet.temp`,
    `cfg.cmd.pellet.wanted`,
  - the startup-patch setpoints (`cfg.adj.pellet.startup.patch.path`
    list),
  - `app.heat.pellet.out` = `{running, since, load, hot,
    pellet_state_code}`.
- **State**: `{t_pellet_on, pellet_on, pellet_load,
  pids: {p_load,p_buffer}}`.
- **Override `value`**: `{load: float}` to force a load setting.

Direct port of `run_set_pellet`. The change-bookkeeping that
currently writes through `self.state.t_pellet_on`, `self.pellet_on`,
`self.pellet_load` becomes `app.heat.pellet.out` (the
published view) plus the unit's own `state` slot.

### 3.5 `selector.py` — WP/pellet decision

Decides which heat source should run. Pure logic; publishes a single
output that `pump` and `pellet` both read.

- **Watches**:
  - sensors: `cfg.sensor.temp.{current,predict}`,
    `cfg.sensor.pellet.state`, `cfg.sensor.buffer.{top,heat,low}`,
  - commands: `cfg.cmd.wp`, `cfg.cmd.heat`,
  - `app.heat.target.out` (`t_nom`, `t_low`, `t_ext_avg`),
  - `app.heat.pump.out` (last known state, for hysteresis).
- **Publishes**:
  - `app.heat.selector.out` = `{choice: "wp"|"pellet"|
    "both"|"none", reason: str, since: ts, ext_avg, wp_ok,
    pellet_ok}`,
  - `cfg.cmd.pellet.wanted` (legacy compatible),
  - `cfg.feedback.pellet` (UI feedback).
- **State**: `{choice, since}`.
- **Override `value`**: `{choice: "wp"|"pellet"|"both"|"none"}`.

Direct port of `run_temp_thresh`, simplified by reading explicit
`target` and `pump` outputs instead of fishing values off `self`.

### 3.6 `errors.py` — error aggregator

Publisher-only unit. Does **not** stop anything itself; the `pump`
unit reacts to `errors.out` going non-empty.

- **Watches**:
  - `cfg.sensor.error` (subtree watch),
  - own config (for the ignore list).
- **Publishes**:
  - `app.heat.errors.out` = `{errors: {path: code, …},
    last_change_ts, severity: "none"|"warning"|"critical"}`.
- **State**: nothing beyond the current published value (which is
  itself retained).
- **Override `value`**: `{errors: {…}}` to inject a synthetic error
  (for maintenance: forces `pump` to `down`).

The emergency-shutdown procedure is **not** in this unit; see §2.5.
The `errors` unit is intentionally minimal so that a crash in error
processing cannot itself prevent shutdown: the pump unit watches the
error feed independently, with stale-error detection.

### 3.7 `moat dev heat watchdog` (optional, separate process)

Not one of the five primary units, but lives in the same package as
`watchdog.py` and is shipped together. Specified here for
completeness:

- **Watches**: `run.app.heat.pump.alive`, `app.heat.pump.out`.
- **Acts**: if `alive` is stale beyond `cfg.watchdog.max_age` and the
  last `out.run` is in the active set (`wait_flow`…`run`, `temp`,
  `ice`), calls `emergency.emergency_shutdown(link, cfg,
  from_pump=False)` (see §2.5). The helper handles the service
  supplant, heat-exchanger off, drain, and water-pump-off sequence.
- **Publishes**: `app.heat.watchdog.out` with the action taken
  (`triggered_at`, `reason`, `duration`, `exit_temp_delta`), for
  auditing.
- **Override**: setting `watchdog.override.mode = "off"` disables
  the watchdog (used during planned maintenance so the operator can
  intentionally take down the pump unit without the watchdog
  immediately reacting).

## 4. Migration

### 4.1 Data migration script (`migrate.py`)

`moat dev heat migrate` performs:

1. Connect to old MoaT-KV and new MoaT-Link.
2. Read the existing yaml config from the file pointed to by `-c` (the
   user's current production config, which is the layered yaml on top
   of the `CFG` literal).
3. Translate it into the six `cfg.app.heat.*` data items
   described in §2.4 (plus optional `…watchdog`), using an explicit
   mapping table (`_CFG_MAP: dict[OldPath, (Unit, NewPath)]`). The
   table is the authoritative source of what moves where; every
   non-deprecated key in the old `CFG` must appear in it or the script
   errors out.
4. Read the persistent state (KV or `/tmp/solvis.state`) and split it
   into per-unit state items at `app.heat.<U>.state`. PID
   integrator slots (`p_flow`, `p_pump`, `p_load`, `p_buffer`,
   `p_limit`, `pp_load`, `pp_buffer`) go to their owning units:
   `flow` gets `p_flow`+`p_pump`; `pump` gets `p_load`+`p_buffer`+
   `p_limit`; `pellet` gets `pp_load`+`pp_buffer`. Run-state fields
   (`run`, `t_change`, `t_run`, `t_load`, `scaled_low`, …) go to
   `pump.state`; `t_pellet_on`, `pellet_on`, `pellet_load` go to
   `pellet.state`; `heat_ok`, `avg_heat`, `avg_heat_t` go to
   `target.state`.
5. Print a dry-run diff (`--dry-run`), or commit with `--commit`.

The script does *not* import the old `solvis.py` code; it works on the
yaml directly. It also produces a small YAML dump of the new structure
to stdout for review.

The migration is one-shot. After running, the user removes the file
`/etc/moat/solvis.yaml` (or whatever) and removes the `state` file from
the host; the new controller only reads from moat-link.

### 4.2 Code switchover

1. Land the new package under `moat/dev/heat/` alongside the
   old `solvis.py`. The old file remains importable but is not wired
   into `_main.py`'s click group during development.
2. Add `heat2` as a hidden click sub-group for testing in parallel.
   Each new unit can be started as `… heat2 <unit>` and
   shadow-deployed (see implementation order in §6).
3. Once the replay-based tests (see §5) pass on recorded data, and
   each unit's shadow-deployment matches the old controller's
   behaviour, swap `_main.py` to point at the new package and delete
   `solvis.py`.
4. Update `docs/moat-dev-heat/index.md` and `README.md`.
5. Bump `packaging/moat-dev-heat/pyproject.toml`:
   - drop `aionotify`,
   - drop `moat-kv` (was implicit),
   - add `moat-link`,
   - bump deps for `moat-util`, `moat-lib-pid`, `moat-lib-run`.
   - run `./mt src tag -s moat.dev.heat -M` for a major-version bump,
     since this is a breaking change.

### 4.3 Removed/relocated features

- File-watched yaml reload (`reload_cfg`, `aionotify`): replaced by
  `d_watch`ing the relevant cfg item in moat-link. Only the `target`
  unit needs live reload (heating curve tweaks); others reload on
  restart. Drops the `aionotify` dependency entirely.
- `run_solvis_mon` (modbus poll babysitter): moved to a separate top-
  level click command (`moat dev heat modbus-monitor`); not a
  unit. Kept in the new package as `modbus_mon.py`.
- The software-PWM background command (`pwm` / `_run_pwm`): kept as is
  in `pwm.py`, since it's an independent daemon already.
- `run_rec` / `run_fake` / `fake_cl` (replay machinery): moved to a
  test helper in `tests/moat_dev_heat/replay.py`, no longer shipped in
  the production package.

## 5. Testing plan

`tests/moat_dev_heat/` currently has only a stub `test_basic.py`. The
plan adds:

```
tests/moat_dev_heat/
    conftest.py            # Scaffold fixture, clock helper, unit-launch helpers
    replay.py              # YAML recording → d_set timeline
    data/                  # recorded runs (small subset, ~1 minute each)
        warmup.yaml
        steady.yaml
        de_ice.yaml
        pellet_start.yaml
        bypass.yaml
        error_then_off.yaml
    test_link_helpers.py   # Reader/Writer/staleness/override semantics
    test_target.py         # heating curve, day/night schedule
    test_flow.py           # PWM PID, de-ice min, stop sequence, staleness
    test_pump_states.py    # transition table (pure function; no link)
    test_pump_replay.py    # full pump unit against recorded data
    test_pellet.py         # p_load/p_buffer, force input, startup patch
    test_selector.py       # WP/pellet decision matrix
    test_errors.py         # err_mon aggregation
    test_pump_shutdown.py  # pump’s safe-shutdown on errors / SIGTERM / crash
    test_watchdog.py       # external watchdog triggers when pump.alive stale
    test_override.py       # per-unit override modes: auto/hold/manual/off
    test_restart.py        # restart a unit mid-run; state resumes via moat-link
    test_migrate.py        # KV-yaml → moat-link items round-trip
    test_integration.py    # all units wired against one Scaffold
```

### 5.1 Fixtures

We build on `moat.link._test.Scaffold`, which already provides an
ephemeral MQTT broker + moat-link server + real `Link` clients in an
`async with` block. Building a separate fake link would duplicate (and
inevitably drift from) retained-message, timestamp, schema-validation,
and `d_watch` semantics. So:

- Each test instantiates `Scaffold(cfg)` and at least one server.
- A `heat_scaffold` fixture in `conftest.py` wraps Scaffold and adds:
  - `await sf.seed_config(unit, dict)` — `d_set` the unit's
    `cfg.app.heat.<U>` item; many tests use a small default
    config produced by `tests/data/cfg_default.py`.
  - `await sf.run_unit(unit_module)` — start the unit's `run()` as a
    background task on the scaffold's task group, against a fresh
    `Link` client. Returns a `UnitHandle` with `cancel()`, `link`,
    and easy accessors for `…<U>.out`, `…<U>.alive`,
    `…<U>.state`.
  - `await sf.feed(path, value, ts=None)` — helper that just calls
    `client.d_set` with optional explicit timestamp.
  - `await sf.expect(path, pred, timeout=2)` — small wrapper around
    `Scaffold.do_watch` that returns the first value matching `pred`
    or raises on timeout.
- Tests that need to assert a *sequence* of published values use
  `Scaffold.do_watch` directly (it already collects into a
  `ValueEvent`).

#### Time control

PIDs and `Reader.fresh()` call `time.time()`. We do *not* monkey-patch
the clock globally; instead, the units accept an injectable
`clock: Callable[[], float] = time.time` via their `run()` signature.
Tests pass a `FakeClock` that the test drives with `clock.advance(s)`.
This is the same pattern already used in `moat.lib.pid` tests.

The real moat-link timestamps (in `MsgMeta`) keep using wall time;
that's fine because the unit code only consults the injected clock
for staleness/PID purposes, not for ordering.

#### Recording playback

`replay.py` reads the existing `record` YAML format (one document per
tick, each containing the historical `Data.__dict__`). It produces a
sorted timeline of `(ts, path, value)` events using a small mapping
table from attribute name (`r_flow`, `t_out`, …) to moat-link path,
and replays them into the scaffold via `client.d_set(…, t=ts)`. The
unit-under-test sees them via its normal `d_watch`.

The mapping table is the same one used by `migrate.py`, so any rename
flows through to both places.

### 5.2 Per-unit tests

- **link_helpers**: pure-Python tests of `Reader.fresh(max_age)`
  against an injected clock; `Writer` debounces equal values;
  `Override` parsing handles `auto` / `hold` / `manual` / `off`,
  expiry, and missing fields. No Scaffold needed.

- **pump_states**: table-driven test of `next_state(…)` as a pure
  function. No Scaffold needed.

- **target**: with Scaffold, start `units.target.run`, seed outside
  temp, advance the fake clock across schedule boundaries, assert
  `target.out.flow_temp` matches the closed-form `vt()` evaluation
  and that day/night force commands flip the result.

- **flow**: feed `r_flow`, `t_out` sequences via `sf.feed`; assert
  PWM stays within `[min,max]`, that `mode=de_ice` clamps to
  `de_ice.min`, that `mode=off` produces 0 immediately. Stop
  feeding `r_flow`, advance the fake clock past `freeze`; assert the
  unit publishes `safe_pwm` and `stable=False`.

- **pump_replay**: replay `data/warmup.yaml` into Scaffold; let the
  pump unit run; collect its `pump.out.run` trace and diff against
  `data/warmup.expected.yaml`. First run records the expected trace
  (manual review); subsequent runs compare. Replay also covers
  steady/de-ice/bypass.

- **pellet**: drive `m_pellet_state` across all interesting
  transitions; assert published `pellet.out` transitions. Test
  `cm_pellet_force` override short-circuits the PIDs.

- **selector**: table-driven; each row sets retained values for
  inputs (via `sf.feed`) and asserts the published `selector.out`.
  Covers on→off and off→on hysteresis edges.

- **errors**: seed entries on the error subtree; assert the
  aggregator's `errors.out` toggles between severity levels. Ignore-
  list config drops specific codes.

- **pump_shutdown**: cover both the in-pump and the supplant paths.
  - In-pump (`from_pump=True`): trigger via `errors.out` becoming
    non-empty, via stale sensors, and via an injected
    `RuntimeError`. Assert the pump unit writes load=0, posts a
    `flow.request={mode:"drain", …}`, waits until either
    `t_out - t_in < stop_delta` (simulated by feeding decreasing
    values) or the timeout, then posts `flow.request={mode:"off"}`,
    and exits. Assert `BaseException` propagates after the shielded
    shutdown completes.
  - Supplant (`from_pump=False`): start a pump unit, then in a
    second task call `emergency_shutdown(link, cfg)`. Assert the
    pump unit exits with `ServiceSupplanted`, the same load=0 /
    drain / off sequence is published by the supplanter, and the
    procedure completes within `total_timeout`.
  - Timeout path: do not feed sensor updates after the heat-
    exchanger off. Assert the procedure ends after
    `emergency.timeout` regardless and that `flow.request={mode:
    "off"}` is still posted.

- **watchdog**: start the pump unit, then cancel it; the watchdog
  detects the stale `pump.alive`, supplants the (now-absent) pump
  service, and runs the full emergency sequence. Assert it writes
  load=0, posts the drain `flow.request`, then `mode:"off"`, and
  publishes a `watchdog.out` audit record. Test the *not*-acting
  case: when last `pump.out.run` was already `off`, no supplant
  happens. Test the override: setting `watchdog.override.mode="off"`
  disables the watchdog even when `pump.alive` is stale.

- **override**: for each unit, write each of the four override modes
  to `….<U>.override` and assert the published output reflects the
  override. Expiry (advanced via fake clock) causes a revert.
  `mode: "auto"` resumes bumplessly (PIDs `move_to`'d).

- **restart**: start a unit, let it run a few simulated seconds with
  fed inputs, `unit.cancel()`, then start a fresh instance against
  the same Scaffold. Because the previous unit's `state` and PIDs are
  retained in moat-link, the new instance resumes with the same
  integrators and state-machine state. Done for `pump` and `pellet`.

- **migrate**: round-trip a small old-style yaml fixture through
  `migrate` against a Scaffold; assert each target path got the
  expected value. Negative test: an unknown top-level key in the
  input raises a clear error.

### 5.3 Integration

`test_integration.py` starts all six units on one Scaffold, replays
`data/steady.yaml`, advances the fake clock for ~60 simulated seconds,
and asserts:

- `pump.out.run` ends in `Run.run`,
- `selector.out.choice` settles on `wp`,
- `target.out.flow_temp` matches the curve,
- `flow.out.pwm` ∈ [0.2, 1.0],
- every unit's `alive` heartbeat ticks at least every 2 s,
- no unhandled exception escapes.

Additional scenarios:

- `data/error_then_off.yaml`: injects an error mid-run; integration
  test asserts the pump's safe-shutdown runs, the pump transitions to
  `off`, the flow unit drops to `safe_pwm`, and load is 0.
- `restart_pump_midrun`: cancel the pump unit's task while others
  keep running; start a replacement after 5 s of simulated time.
  Depending on configured `watchdog.max_age`, the watchdog may or may
  not have fired; the test asserts the appropriate outcome.

### 5.4 Test execution

- All tests use `pytest -q`. Recorded comparisons are written to a
  temporary file first (per `AGENTS.md`), then diffed. Recording
  refresh is via `pytest --update-references`, gated on a flag so CI
  cannot silently update.
- The Scaffold spins up a real MQTT broker per test; tests are
  written to be quick (typically <2 s wall time each) and to set
  short `ping.cycle`/`startup` values like the existing
  `tests/moat_link/` tests do.
- `ty check --output-format github` must pass for all new modules.
  Modules are added to `tool.ty.src.include` in
  `packaging/moat-dev-heat/pyproject.toml` as they go green.
- `ruff format` + `ruff check` clean.
## 6. Implementation order

A sequence of self-contained commits, each building and testing on
its own. Because units are independent processes, the order is
flexible after step 2; we follow this order to minimise risk on the
production system.

1. **Scaffold and link helpers.** Create the new unit-module
   skeleton under `moat/dev/heat/` with empty unit modules,
   `config.py`, `state.py`, `link.py` (Reader / Writer / Override /
   Heartbeat), `emergency.py`. Tests: `test_link_helpers.py`. No
   behavioural change; old `solvis.py`
   still drives the click commands.

2. **Migration script.** Implement `migrate.py` +
   `test_migrate.py`. Run it against the production config (manually)
   to generate the real config items. After this step the operator
   can write to the config paths and we have ground truth for the
   per-unit configs.

3. **`target.py`** + `test_target.py`. Deploy it as a hidden
   click command `… heat2 target` running side-by-side with the
   old controller; verify its published output against the old
   `heat_dest`. Once the published output is correct, point the old
   controller at `target.out` instead of its in-line computation
   (one-line change in `solvis.py`).

4. **`flow.py`** + `test_flow.py`. Same shadow-deploy pattern:
   run the new unit and compare its computed PWM with the old
   controller's, without actually driving the output, until they
   agree. Then switch the actual output over.

5. **`errors.py`** + `test_errors.py`. Trivial; mostly a
   port of `err_mon`.

6. **`pellet.py`** + tests. Once `target` and `errors` are
   live, `pellet` can run as its own process. Shadow-deploy first:
   compare published `pellet.out` with the old controller's state
   before switching the actual `cmd.pellet.*` writes over.

7. **`selector.py`** + tests. Smaller change; can also
   shadow-deploy.

8. **`pump.py`** + `test_pump_states.py`, `test_pump_replay.py`,
   `test_pump_shutdown.py`. The largest single change. Cannot easily
   be shadow-deployed because it owns the load output, so it lands
   together with steps 6–7's output cutover during a planned
   maintenance window. The recordings collected in step 3 are used
   for regression.

9. **`watchdog.py`** + `test_watchdog.py`. Optional but
   deployed alongside `pump`.

10. **Integration and cleanup.** Wire all units in
    `system/runner.py:run_all()`, add `test_integration.py` and
    `test_restart.py`, hook `_main.py` to start them all by default.
    Delete `solvis.py`, drop `aionotify`/`moat-kv` deps, bump
    version, update docs, close all the per-unit issues.

## 7. Risks and open questions

- **PID tick cadence.** Sensor updates that drive PID gains (`r_flow`,
  `t_out` for `flow`; buffer temps for `pump`'s `load`) arrive via
  moat-link today already, so the cadence does not change for those.
  Inter-unit signals (`target`, `selector`) do not feed PIDs directly,
  so going through MQTT for them is fine. Action: a single regression
  test on a recorded run that compares pre-/post-split PID outputs.

- **Restart bumpiness.** When a unit restarts, its PIDs reload their
  integrators from `…<U>.state`. If the unit crashed between PID
  evaluations, the integrator on disk is one tick stale. For the
  primary PIDs this is fine; the flow PID is the most sensitive and
  uses `move_to(value)` on the first tick after restart to avoid a
  step in the output. Tested in `test_restart.py`.

- **Flow unit unavailable during emergency.** The emergency procedure
  publishes `flow.request` and trusts the `flow` unit to honour it.
  If the flow unit is also dead, residual heat cannot be removed and
  the Solvis controller's hardware safety limits (over-temperature
  cutout) are the last line of defence. We could optionally have the
  emergency helper also `announcing(force=True)` the flow service
  and drive PWM directly; deferred until we see this in practice.
  Action: document the dependency in the package README.

- **Self-supplant race.** When the pump unit's `finally` block runs
  `emergency_shutdown(from_pump=True)`, the unit is still inside its
  `announcing` context. The helper must not attempt to take the
  service again; the `from_pump` flag guards this. Tested in
  `test_pump_shutdown.py`.

- **Override race with retained writes.** An operator setting
  `…override = {mode: "off"}` and then the unit publishing its
  computed `out` could leave both messages retained. Convention: the
  unit's `out` always reflects what the unit *actually published to
  downstream paths*, including any override translation. So
  consumers only ever look at `out`, never need to reconcile with
  `override` themselves.

- **Heat-valve placement.** Currently in the tail of `run_pump`. The
  plan puts it in `target.py` because it belongs to the
  heating-distribution side, not the heat-source side. Confirm with
  the operator; if not, split it out as `heat_valve.py`.

- **Schema validation.** moat-link's `d_set` can validate against a
  schema (see `moat.link.schema`). We define schemas for each
  `cfg.app.heat.*` and `app.heat.*.out` item and
  publish them, so that malformed writes (especially from manual
  override) are rejected at the source.

- **Recording format.** The old `record`/`replay` format dumps the
  whole `Data.__dict__`. With per-unit isolation there is no central
  object; recording happens by `d_watch`ing the relevant paths on a
  side-car process (`moat dev heat record`). Replay feeds the
  recorded stream back into a FakeLink. This is also what
  `test_pump_replay.py` uses.

- **Two operators writing the same override path.** moat-link
  retains the last write; there is no locking. Operators must
  coordinate. The `reason` and `expires` fields plus the `alive`
  heartbeats let a TUI display who set what and when.
