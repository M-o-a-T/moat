# Refactoring the `moat.dev.heat` Solvis controller

`moat/dev/heat/solvis.py` is a single ~2300-line module that implements
the whole heat-supply controller (heat pump, pellet boiler, heating
curve, heating-circuit valve, flow control) as one big `Data` class on
top of MoaT-KV, plus a YAML config literal. This document plans its
split into independent, testable units communicating via MoaT-Link.

The goal is a clean rewrite with a **clean cutover**. Incremental
switch-over, shadow deployment, on-disk-state compatibility and
KV/Link parallel operation are **non-goals**: all of them would keep a
dependency on MoaT-KV, which is to be removed. Correctness before
cutover is established with a plant simulator and with reference
traces recorded from the legacy code running against that simulator
(§5).

The epic tracking this work is `moat-n84` in Beads.

## 1. What the existing code does

| Concern | Current location | Notes |
| --- | --- | --- |
| Heat-pump state machine | `run_pump` | `Run` enum: off → wait_time → wait_flow → flow → wait_power → temp → run, plus `ice` and `down`. Entry actions and per-state ticks are interleaved in one loop. |
| Demand setpoints | `run_pump`, middle | `t_nom`/`t_low`/`t_adj`/`t_set_on`/`t_set_off` and the measured `t_cur` from `c_water`, `c_heat`, `cm_heat`, `adj.*`. Also consumed by pellet and selector code via `self`. |
| Heat-pump load control | `run_pump`, end | PIDs `load`, `buffer`, `limit` (load) and `pump` (PWM); `w` blend, `scaled_low` decay, OFF rules 3/4/5/6/SCALED. |
| Pellet setpoint writes | `run_pump` | `cmd.pellet.temp` and the startup-patch goals are written on every tick. |
| COP estimator | `run_pump` | Writes `sensor.cop` every 100 ticks. |
| Heating-circuit valve | `run_pump`, tail (`log_hc` 1…11) | Switches `setting.heat.mode.path` (and optionally a GPIO pin). |
| Water-pump PWM | `set_flow_pwm`, `handle_flow`, `pid.flow`/`pid.pump` | Fixed PWM, flow PID, `max(flow, temp)` and temp-PID-only modes depending on pump state. |
| Pellet burner load | `run_set_pellet` | State-code classification, tri-state `t_pellet_on`, `p_load`/`p_buffer` PIDs; also changes `pid.load` Kd/Tf. |
| WP vs. pellet | `run_temp_thresh` | Boolean "pellet wanted"; evaluated every 10th update; resets pellet state and preloads pellet PIDs. |
| Heating curve | `run_set_heat` + `vt()` | Outside temp + weekday/weekend night schedule + day/night force switches → `adj.curve.setting`. |
| Error monitor | `err_mon` | Watches `sensor.error`; ignores code 30055 and path `:1`; vetoes WP run. |
| Bypass | `run_pump`, start | Manual mode: `c_flow`/`c_bypass_mode`/`c_bypass_power` passed straight to outputs. |
| Controlled stop | `off`, `run` finally | Load 0, flow until ΔT < `misc.stop.delta` or `lim.times.stop`, then PWM 0. |
| Config + state | `CFG` literal, `-c` file (`aionotify` reload), `/tmp/solvis.state` or a KV path, `saver` | Also reads `/etc/moat/moat.cfg` at import time. |
| Recording / replay | `record=`, `run_rec`, `run_fake`, `fake_cl` | Dumps `Data.__dict__` per update. |
| KV plumbing | `_kv`, `has`, `wait`, `all_done`, `trigger` | Maps KV paths onto attributes of `self`. |
| Software PWM | `pwm` / `_run_pwm` (click cmd) | RPi.GPIO; separate daemon, uses MoaT-KV. |
| Modbus babysitter | `run_solvis_mon` | Restarts `moat modbus dev poll` on Solvis error code 26; uses MoaT-KV. |

Known quirks of the legacy code that the rewrite must not copy blindly:

- It writes its run state to `sensor.pump.state` (`heat.s.pump.state`),
  which is also the `dest` of the heat pump's modbus poller (the real
  WP state) and the `src` of the Solvis shim. The new pump unit
  publishes its state in `app.heat.pump.out`; whether the shim relies
  on the overwritten value is to be clarified during the path audit.
- PID state stores `time.monotonic()` timestamps, which are meaningless
  after a restart.
- The selector's decision cadence depends on the update rate of
  unrelated values.

## 2. Target architecture

### 2.1 Units and package layout

Each unit is independently restartable and runs as its own process
(`moat dev heat <unit>`); `moat dev heat run` starts all of them in one
task group for single-host setups. Units communicate only through
MoaT-Link. There is no shared in-process state.

Units:

| Unit | Role |
| --- | --- |
| `target` | Heating curve, day/night schedule, demand setpoints. Pure function of outside temperature, schedule, settings and overrides. |
| `heat_valve` | Heating-circuit on/off (later: circulation-pump speed). |
| `flow` | Water-pump PWM; serves flow requests. |
| `pump` | Heat-pump state machine and load control. |
| `pellet` | Pellet burner load control. |
| `selector` | Which heat source(s) should run, including handover and fallback. |
| `errors` | Error aggregation (publish only). |
| `watchdog` | Optional; emergency shutdown if the pump unit dies while active. |
| `passthru` | Coordinates handing the heat pump to its original controller for maintenance (§2.8). |

`moat dev heat run [UNIT…]` (`system/runner.py`) runs the named units,
or all but the watchdog, each on its own MoaT-Link client, and talks to
systemd.

- Without arguments, each unit waits until nobody else announces its
  service. A unit that fails is logged, reported to MoaT-Link's error
  subsystem (`error.app.heat.<unit>`) and restarted with exponential
  backoff (`cfg.app.heat.service`: `backoff.min/max/factor`; the error
  is cleared and the delay reset after `recovery` seconds of running).
  A unit that is supplanted (e.g. by `moat dev heat off`) waits for its
  service and then resumes.
- Named units take their service over from whoever runs it (for
  debugging). A failure is reported to MoaT-Link and ends the command.

The package `moat-dev-heat-service` installs the systemd units:
`moat-heat@UNIT.service` per unit, `moat-heat.service` for all of them
in one process, `moat-heat-pwm.service` and
`moat-heat-modbus-mon.service`.

Support commands: `off` (emergency shutdown), `curve` (print the
heating curve), `migrate`, `sim` (plant simulator on MoaT-Link),
`record` (side-car recorder), `pwm` and `modbus-monitor` (ported
daemons).

```
moat/dev/heat/
    __init__.py
    _cfg.yaml         # package defaults, one subtree per unit
    _main.py          # click group: every unit + support commands
    kwb.py            # KWB modbus helper (unchanged)
    config.py         # pydantic config models, config loader (§2.4)
    link.py           # Reader, Writer, input merging, override readers, service monitor
    state.py          # per-unit persistent state
    pid.py            # APID: CPID with persistable state and Link logging
    unit.py           # Unit base: sans-IO core + Link adapter
    emergency.py      # emergency_shutdown() (§2.6)
    target.py
    heat_valve.py
    flow.py
    pump.py           # core (state machine) + adapter
    pellet.py
    selector.py
    errors.py
    watchdog.py
    passthru.py
    record.py         # side-car recorder / open-loop replay
    pwm.py            # software PWM daemon, ported to MoaT-Link
    modbus_mon.py     # Solvis poll babysitter, ported to MoaT-Link
    sim/              # plant simulator (§5.3)
        __init__.py   # sans-IO model (plant.py, buffer.py, heat_pump.py, …)
        paths.py      # where sensors and commands live in MoaT-Link
        loop.py       # closed-loop runner: plant + unit cores, by path
        trace.py      # trace recording and comparison
        link.py       # MoaT-Link adapter
    system/
        runner.py     # `moat dev heat run`
        migrate.py    # one-shot KV/YAML → Link migration
```

Every unit consists of

- a **sans-IO core**: a class whose `step(inputs, now)` returns a
  `unit.Step` (outputs, state-save request, next wake-up delay), with
  no I/O, no clock access and no MoaT-Link dependency; and
- a thin **Link adapter**, a subclass of `unit.Unit`, which loads the
  config, watches inputs, feeds the core, writes outputs, persists
  state and announces the service.

This split lets the cores run in closed loop against the simulator in
simulated time (§5), while the adapters are tested against a real
MoaT-Link test server.

### 2.2 Inter-unit communication

Everything one unit needs from another is `d_watch`ed; everything a
unit wants others to see is written with `d_set(..., retain=True)`.
A restarting unit therefore receives the last retained value of every
input immediately.

#### Path layout

| Path | Written by | Retained | Contents |
| --- | --- | --- | --- |
| `cfg.app.heat.<U>` | operator / `migrate` | yes | unit config (§2.4) |
| `app.heat.<U>.out` | unit `U` | yes | the unit's published view (per-unit specs in §3) |
| `app.heat.<U>.state` | unit `U` | yes | persistent state (§2.3) |
| `app.heat.flow.request` | `pump`, `emergency_shutdown` | yes | the flow unit's input (§3.3) |
| `app.heat.override.*` | operator / HA bridge | yes | operator overrides (§2.7) |
| `app.heat.passthru.request`, `….state` | operator / `passthru` | yes | passthru mode (§2.8) |
| `app.heat.force_start` | CLI / operator | yes, cleared by `pump` | one-shot "start now" (§3.4) |
| `app.heat.watchdog.disable` | operator | yes | disables the watchdog (§3.8) |
| `run.host.<host>.heat.<U>` | unit `U` | (announce) | service announcement / liveness |

Sensor and physical-output paths (`heat.s.*`, `home.ass.*`,
`temp.*`) keep their locations; they are not owned by this package.
Each unit's config maps them to the unit's inputs and outputs.
Units use the native names; `heat.*` and `temp.*` currently reach
them via the MoaT-KV gateways, which go away at cutover. [PATHS.md](PATHS.md) lists every path with its current location,
type, update rate and known gaps.

#### Liveness

Units announce themselves with `moat.link.announce.announcing` under
`run.host.<host>.heat.<U>`. `<host>` is configurable; the default is a
fixed installation-wide name (`heat`), not the machine's hostname, so
that a watchdog or operator command running on another machine
addresses the same service. MoaT-Link's own liveness tracking (removal
of the announcement when the client's pings stop; `error.run.host.…`
entries) is the only liveness signal. There are no separate heartbeat
topics.

A small `ServiceMonitor` helper in `link.py` exposes "is service `X`
alive" from the announcement for the watchdog and for UIs.

#### Reading inputs

`link.Reader[T]` wraps one `d_watch(path, meta=True)`:

```
class Reader[T]:
    value: T | None          # last value, None until first message
    ts: float | None         # MsgMeta timestamp of that value
    def fresh(self, now: float, max_age: float) -> bool
    async def wait_value(self) -> T
```

A unit merges its readers into one "some input changed" stream and
feeds a snapshot of all readers to its core. Timer-driven work (PID
ticks, delays, schedule boundaries) is requested by the core as a
delay until the next wake-up and handled by the adapter (§5.2).

#### Staleness

Values are published on change, and the Modbus poller re-sends a steady
value every 120 s (its registers' `idem`), so every received update,
changed or not, means the value is current. An input's age is the age
of its datum's timestamp (`Reader.age`); the first value counts as at
most 9/10 of the reader's `max_age` old, so it gets at least a tenth of
the timeout to be renewed. Adapters pass the ages to their cores as
`inputs["_age"]`. Each input has a configurable `max_age`. Default
reactions:

- `pump`: a stale critical sensor (`t_in`, `t_out`, `r_flow`,
  `m_power`, buffer temperatures) while active → emergency shutdown
  (§2.6). While `off`, stale inputs only prevent starting.
- `flow`: stale `r_flow`/`t_out` → hold the last PWM for `freeze`
  seconds, then `safe_pwm`. Never 0 unless the request says `off`.
  A stale *request* is treated as still valid (it is retained), but
  a request older than `request_max_age` while the pump service is
  not alive falls back to `safe_pwm` until ΔT < `stop_delta`, then 0.
- `pellet`: hold the last load, drop to 0 after `freeze`.
- `selector`: latch the last decision; never switch on stale data.
- `target`: hold the last setpoint; after `freeze`, use the curve at
  `curve.dest`.
- `heat_valve`: hold the current valve state.
- `errors`: a stale error feed becomes a synthetic error entry.

#### Writing outputs

`link.Writer` keeps a last-value cache per path and skips unchanged
writes (the replacement for MoaT-KV's `idem=True`).

### 2.3 Persistent state

Each unit owns `app.heat.<U>.state`; there is no shared state object.
`state.State` (a pydantic model) provides `load(link)` (defaults when
absent), `save(link)` (debounced, default 10 s) and an immediate-write
flag used for critical changes such as pump state transitions.

PID state (`i`, `e`, `setpoint`, `t`) is kept inside the owning unit's
state (e.g. `PumpState.pids.load`). `pid.APID` runs on monotonic time but
persists its timestamp as wall-clock time, so that the integrator does
not jump after a restart; on load, a timestamp older than a configurable
limit is re-based to "now" so that the first step after a long outage
does not integrate over the outage. `APID` also publishes value and setpoint to the configured
`log.value` / `log.setpoint` paths, as in production today.

All timestamps in unit states work that way (`pid.MonoTime`): monotonic
in memory, wall-clock time when persisted, so they survive a reboot
(e.g. the pump's `t_load`, which gates the next start).

### 2.4 Configuration

Each unit has exactly **one** configuration object, obtained as

```
combine_dict(<MoaT-Link item cfg.app.heat.<U>>, <package default>)
```

with the MoaT-Link item taking precedence. The package defaults live in
`moat/dev/heat/_cfg.yaml` (registered via `moat.lib.config`, i.e.
available under `CFG.dev.heat.<U>`). The unit monitors its Link item;
on every change the merged result is re-validated into the unit's
pydantic model and handed to the unit as a fresh instance. All units
support live reload; an invalid update is logged and ignored (the
previous config stays active); deleting the item reverts to the
defaults.

Config models subclass `moat.lib.config.base.BaseModel`. That base
class needs some extensions first (separate issue, label `common`):
`moat.lib.path.Path` fields that accept `Path` or `str` and survive the
Link codec round-trip, validation of (nested) `attrdict` input, a
`from_cfg(path)` classmethod, and a `monitor()`-style helper yielding
re-validated instances.

Each unit's config contains every path it needs, so units stay
independent. The small duplication (e.g. `app.heat.target.out` appears
in several unit configs) is intentional; `migrate` generates
consistent values.

Shared items:

- `cfg.app.heat.emergency`: tunables of the emergency procedure (§2.6),
  read by `pump`, `watchdog` and `off`.
- `cfg.app.heat.service`: the service host name (default `heat`).

The Modbus bridge configurations (`/etc/moat/modbus.*.yaml`) stay
file-based; runtime reconfiguration of `moat modbus dev poll` from
MoaT-Link is a separate, deferred issue.

The module-level `open("/etc/moat/moat.cfg")` goes away; the MoaT-Link
connection is configured through the standard `moat.link` config.

### 2.5 Heat-pump liveness under supplant

The `pump` unit announces `run.host.<host>.heat.pump`. Any process
announcing the same service with `force=True` supplants it: the pump
unit's announcement monitor raises `ServiceSupplanted`, and the pump
unit exits **without** touching any output — the supplanter owns the
shutdown procedure. `ServiceSupplanted` may arrive wrapped in an
`ExceptionGroup`; the pump unit unwraps it for this decision.

A pump unit restarted by systemd while another process owns the
service is itself supplanted on startup (the announce is not forced),
exits, and is retried by systemd. This is intended: the pump comes
back after the emergency procedure has released the service.

### 2.6 Emergency shutdown

The water pump must not stop while the heat exchanger still produces
heat. Emergency shutdown is therefore a sequence, implemented once in
`emergency.emergency_shutdown(link, cfg, *, from_pump: bool)` and used
by the pump unit, the watchdog and `moat dev heat off`:

1. Unless `from_pump`: enter `announcing(link, <pump service>,
   force=True)`, supplanting any running pump unit (§2.5).
2. Write load 0 and the configured "off" value to the heat pump's
   power/mode command paths.
3. Publish `app.heat.flow.request = {mode: "drain", rate:
   emergency.flow_rate}`.
4. Wait until either `emergency.timeout` (default 120 s) elapses, or
   `t_in` and `t_out` are both fresher than `emergency.max_sensor_age`
   (30 s) and `t_out - t_in < emergency.stop_delta` (3 °C). The sensors
   may be the reason for the shutdown, so the timeout is the
   unconditional safety net.
5. Publish `app.heat.flow.request = {mode: "off"}`.
6. Unless `from_pump`: leave the `announcing` block, releasing the
   service.

The whole sequence runs inside `anyio.move_on_after(
emergency.total_timeout)` (default 180 s).

The pump unit calls it with `from_pump=True` (shielded, bounded by
`total_timeout`) on abnormal exit only:

- `errors.out` reports a critical error while the pump is active,
- a critical sensor is stale while active,
- the core raises its start-up timeout (`t_change_max` exceeded),
- an unexpected exception escapes the main loop,
- the unit is cancelled while active.

It does **not** call it on `ServiceSupplanted`. Afterwards the original
exception is re-raised; `BaseException`s (including cancellation)
always propagate after the shielded shutdown completes. The normal
`down` → `off` path handles routine shutdown.

The procedure depends on the `flow` unit being alive. If it is not,
the heat pump's own over-temperature cutout is the last line of
defence. Having the helper also supplant the flow service and drive
PWM directly is deferred until needed; the dependency is documented in
the package README.

`cfg.app.heat.emergency`:

```
flow_rate:      12     # l/min while draining
timeout:        120    # s, max cool-down wait
stop_delta:     3.0    # °C, t_out - t_in threshold
max_sensor_age: 30     # s
total_timeout:  180    # s
power_path:     !P heat.s.pump.cmd.power
mode_path:      !P heat.s.pump.cmd.mode
mode_off:       0
sensor_in:      !P heat.s.pump.temp.in
sensor_out:     !P heat.s.pump.temp.out
```

### 2.7 Operator overrides

Overrides replace the old bypass mode and the per-unit override of
earlier drafts. They are plain retained data items:

| Path | Type | Meaning |
| --- | --- | --- |
| `app.heat.override.wp` | `bool \| None` | heat pump forced on / forced off / automatic |
| `app.heat.override.pellet` | `bool \| None` | pellet burner forced on / forced off / automatic |
| `app.heat.override.flow_temp` | `float \| None` | intended flow temperature / automatic |
| `app.heat.override.pwm` | `float \| None` | water-pump PWM / automatic (flow unit) |
| `app.heat.override.errors` | `{key: code} \| None` | injected errors (errors unit; always in the `{value: …}` form) |

Each item may instead hold `{value: …, expires: <epoch>, reason: str}`;
after `expires` the consumer treats it as `None` (automatic) and
publishes an event saying so. Schemas are published via
`moat.link.schema` so that malformed writes are rejected.

- The **selector** honours `wp` and `pellet` (True = this source runs,
  False = it never runs, not even as a fallback).
- **`pump`** and **`pellet`** also honour `False` directly, so that
  "off" works even when the selector is down.
- **`target`** replaces the computed flow temperature by
  `flow_temp`; `target.out` reports computed and effective values.

The existing Home Assistant switches (`…heizung.wp.cmd`,
`…heizung.pellets.cmd`, day/night force) are mapped onto these items
by configuration, not by code in the units.

Implementation (`override.py`): `OVERRIDES` lists the items and their
types; `publish_schemas()` stores their JSON schemas (a plain value,
`null`, or the `{value, expires, reason}` form) below
`schema.app.heat.override`; `set_override()` and `moat dev heat
override NAME VALUE [-t seconds] [-r reason]` write them. Consumers use
`override.reader()`: a value of the wrong type reads as `None`, and an
expired item is deleted, so every consumer and the operator's UI see it
lapse.

Home Assistant: the units don't read or write HA entities. Jobs on the
main node copy them to and from `app.heat.ha.*`, and show each override
item as a value entity plus a "manual" switch (job snippet
`transform.hass.override`); see `examples/moat-dev-heat/HA.md`. The legacy
`wp.cmd` switch (off = heat pump off, on = automatic) becomes the pair
`heizung.wp` / `heizung.wp_override`.

### 2.8 Passthru mode

For manufacturer maintenance, the original heat-pump controller (the
Solvis controller, talking to our Modbus shim, currently
`modbus.stiebelfake.yaml`) must control the heat pump (the bus polled
via `modbus.stiebel.yaml`) directly. Our pump controller is then
replaced by a data bridge. The legacy code did this with
MoaT-KV data; the new design uses MoaT-Link and the switchable `bypass`
of `moat.modbus` server units (moat-nnz, see
`docs/moat-modbus/dev-poll.md`):

- The shim's server unit has `bypass: {when: [!P
  app.heat.passthru.state, !P bypass], dest: …}`, pointing at the unit
  that the `modbus.stiebel.yaml` poller serves for the heat pump. While
  bypassed, it forwards every read and write verbatim, via Modbus-TCP.
- That poller's client unit has `bypass: {when: …}` (same flag, no
  `dest`): it then executes those requests on the heat pump directly,
  and pauses its own `src` writes (our `cmd.*` values).

Real passthru needs forwarding because the original controller's reads
must see live data, not stored values. The two Modbus processes stay
separate.

The `passthru` unit (`passthru.py`) coordinates the switch:

- Input `app.heat.passthru.request` (bool; HA switch
  `switch.heizung.passthru`). Output `app.heat.passthru.state` =
  `{bypass: bool, switching: str|None}`: whether the original controller
  is in charge, and what a pending switch waits for (`heatpump_idle`,
  `sensors`, `solvis`), `None` when settled. This is the unit's
  persistent state, saved at once, so a restart resumes.
- The switch happens **only while the heat pump is idle**: power below
  `p_idle` and compressor speed 0; towards the original controller also
  `pump.out.run == off`. Otherwise the request waits. While a switch to
  the original controller is pending, the pump unit doesn't start the
  heat pump (a running one finishes normally).
- While bypassed:
  - the pump unit sends no commands to the heat pump, but runs the
    circulation pump as the Solvis says: its flow request is `fixed` at
    the Solvis' pump output `heat.s.pump.rate.cmd` (`analog.out:4`, a
    PWM duty cycle, polled every second), or at `bypass_pwm` while that
    has no value. `pump.out` shows `run: off`, reason `passthru`;
  - the watchdog is inactive, the shim forwards everything, and sensor
    data keeps flowing to MoaT-Link;
  - the other units carry on: they see an idle heat pump;
  - the shim's `de_ice.fake` doesn't matter: the Solvis reads the real
    register through the bypass.
- When the bypass ends, the pump unit restarts its state machine, which
  begins with `down`: heat pump off, circulation pump on until
  `t_out - t_in` is small. That step re-sends all of its outputs, as the
  heat pump's commands are the Solvis' at that point.
- **Emergency end**: if the Solvis can't be polled, `rate.cmd` freezes,
  so our circulation pump no longer follows it while it may raise the
  heat pump's power. The passthru unit watches the error records listed
  in its `errors` setting (below `error`: the Solvis host's poll errors,
  `app.modbus.tcp.<host>.<port>…`, and the Solvis poller's service,
  `run.host.…`, which `moat-link-host` reports when the poller is gone).
  Any record ends the bypass at once and resets the request; the pump
  unit then cools the heat pump down as above. A record also blocks
  entering the bypass (`switching: solvis`).

## 3. Unit specifications

Notation: **Watches** (each becomes a `Reader`), **Publishes**
(retained unless noted), **State** (`app.heat.<U>.state`). All units
also watch their config (§2.4) and announce their service (§2.2). Path
names are those of the current production config; the actual paths
come from each unit's config.

### 3.1 `target` — heating curve and demand

Pure function of outside temperature, schedule, settings and
overrides. Does not depend on other units.

- **Watches**: `adj.curve.current` (outside temperature for the curve;
  production: `temp.avg.temp.aussen_kompost.min`), day/night force
  switches `setting.heat.mode.force.{day,night}.cmd`,
  `setting.heat.day` (`c_heat`), `setting.water` (`c_water`),
  `cmd.heat` (`cm_heat`), `app.heat.override.flow_temp`.
- **Publishes**:
  - `adj.curve.setting` (`heat.s.heat.temp.cmd`) = `int(flow_temp + 0.8)`,
    the Solvis-facing heating setpoint,
  - force-switch feedback `setting.heat.mode.force.{day,night}.state`
    (setting one clears the other),
  - `app.heat.target.out` = `{flow_temp, flow_temp_computed,
    overridden, day_active, t_ext, t_ext_stale, demand: {t_nom, t_low, t_adj,
    t_set_on, t_set_off, source}}` where `source` is `heat` or
    `water` (which buffer sensor `t_cur` refers to: `tb_heat` when
    heating is enabled, else `tb_water`).
- **State**: `{locks: {day, night}}`.

`flow_temp` is `vt(t_ext, dest, curve)` with `dest` from the
weekday/weekend night schedule (`night.start.{wk,we}`,
`night.stop.{wk,we}`; note the legacy code uses the weekend stop time
on Fridays and Saturdays, the weekend start time on Saturdays and
Sundays) or a force switch. The unit wakes at the next schedule
boundary; its adapter passes the local date and time to the core as an
input (`Unit.local_time`; the closed-loop runner passes simulated local
time). `t_ext` is the last outside-temperature
reading (the legacy name `t_ext_avg` was misleading). Demand values are
the port of the `tw_*`/`th_*` computation in `run_pump`; with heating
off (or `cm_heat` unknown) they are the water values only.

The outside temperature counts as stale when it has not changed for
`max_age` (default 1 h) or was deleted; its last value is used for
another `freeze` (default 1 h), then `flow_temp` drops to `dest`, the
curve's lower end. A force switch that turns on clears the other one's
`cmd` and `state`; the locks are kept in the state. The switches are
read with `link.Switch`, which counts changes made by others (the
message's origin is not our client), so the unit's own writes, and old
values those writes have not replaced yet, are never taken for an
operator's action. `moat dev heat target curve [-d]` prints the curve
(outside, day and night flow temperature) from the live or the package
default config.

Implementation: `target.py`.

### 3.2 `heat_valve` — heating circuit

Port of the tail of `run_pump` (`log_hc` 1…11). Kept separate from
`target` because it depends on the heat source's operating state.

- **Watches**: `pump.out` (run state, `heat_off` flag of the current
  state), `flow.out` (`pwm`), `pellet.out` (`t_pellet_on`),
  `target.out` (`demand.t_adj`), sensors `tb_heat`, `tb_low`, `t_out`,
  `misc.switch.state` (`m_switch`), `setting.heat.day` (`c_heat`),
  `cmd.heat` (`cm_heat`).
- **Publishes**: `setting.heat.mode.path` (on/off value), optionally
  `feedback.pump`, `feedback.heat` (echo of `cm_heat`),
  `app.heat.heat_valve.out` = `{on, pending, hc, reason}`.
- **State**: `{heat_ok, pending}` (on; ok since, while waiting).

Rules (from the legacy code): heating on after `mode.delay` seconds of
"ok"; the pre-heat test blends `tb_heat` and `t_out` by
`pwm / adj.low.pwm`; heating is forced on during `temp` when
`tb_low + misc.heat.delta > t_adj`; heating is **never switched off
while the heat pump is in `run`** unless `m_switch` is set, because
the sudden warm return would overload the heat pump.

The GPIO heat-pin output of older configs is supported only as an
interim option; replacing it with a Modbus circulation-pump speed
controller is a follow-up issue. The unit has no GPIO code: its optional
`pin` output (1.0/0.0) can drive a `pwm` daemon output.

Implementation (`heat_valve.py`): the state is `{heat_ok, pending}`,
`pending` being the monotonic time since which the circuit is ok while
the delay runs (restarted after a restart). `out` is `{on, pending, hc,
reason}`; `hc` is the legacy `log_hc` number, extended by 12 (too cold
while the heat pump runs, circuit off), 13 (pellet burner), 14 (heating
disabled) and 15 (an input is missing: the circuit is held as it is,
also when `cm_heat` is unknown).

### 3.3 `flow` — water-pump PWM

Owns `pid.flow` (flow rate → PWM) and `pid.pump` (outflow temperature
→ PWM) and the PWM output path (`output.flow.path`, read by the `pwm`
daemon or a hardware driver).

- **Watches**: `sensor.pump.flow` (`r_flow`), `sensor.pump.out`
  (`t_out`), `app.heat.flow.request`, `app.heat.frost.out` (§3.11).
- **Publishes**: PWM output, `app.heat.flow.out` = `{pwm, mode,
  stable, request_seq}`; `request_seq` is the `seq` of the request in
  effect. Besides the request modes, `mode` can be `override`, `freeze`
  and `safe` (stale sensor), `fallback` and `idle` (no trusted request),
  and `frost` (a frost-protection pulse, used while the PWM would
  otherwise be 0 and there is no override).
- **State**: PID slots `flow`, `pump`.

Request (`app.heat.flow.request`, written by the pump unit and by
`emergency_shutdown`):

```
{ mode: "off" | "fixed" | "rate" | "rate_temp" | "temp" | "drain",
  pwm: float | None,        # "fixed"; also preload value
  rate: float | None,       # "rate", "rate_temp", "drain": flow setpoint
  temp: float | None,       # "rate_temp", "temp": t_out setpoint (t_pump)
  min_pwm: float | None,    # lower clamp (de-ice: misc.de_ice.min)
  preload: bool,            # move_to(setpoint, pwm) on change
  seq: int }                # increments on every change
```

| Mode | Legacy use | Output |
| --- | --- | --- |
| `off` | `off`, `wait_time` | 0 |
| `fixed` | `wait_flow` (init pwm), `temp` entry | `pwm` |
| `rate` | `flow`, `wait_power` | `pid.flow(r_flow)` |
| `rate_temp` | `temp`, `down`, `ice` (`handle_flow`) | `max(pid.flow, pid.pump)`, ≥ `min_pwm` |
| `temp` | `run` | `pid.pump(t_out)`; 1.0 if `t_out > adj.max_max` (with `move_to`) |
| `drain` | emergency | `pid.flow` at `rate`, ≥ `safe_pwm` |

The request is written with plain types (`FlowRequest.to_link()`). A
sensor counts as stale when it has not been updated for `max_age`
seconds (300; the poller re-sends steady values every 120 s). A PID
whose output is not used follows the time without integrating.

The pellet unit never requests flow. `flow.out.pwm` replaces the old
`state.last_pwm` for its consumers (`pump`, `heat_valve`).

### 3.4 `pump` — heat-pump controller

Heat-pump state machine and load control only: no pellet, heating-
valve or source-selection logic, no direct PWM output.

- **Watches**: sensors `sensor.pump.{in,out,flow,ice}`,
  `sensor.buffer.{top,heat,mid,low}`, `sensor.power`,
  `misc.switch.state`; peer outputs `target.out`, `selector.out`,
  `pellet.out`, `errors.out`, `flow.out`, `passthru.state`;
  `app.heat.override.wp`; `app.heat.force_start`.
- **Publishes**:
  - heat-pump commands `cmd.power`, `cmd.mode.path` (load below
    `lim.power.min` → power 0 + mode off),
  - `app.heat.flow.request` (§3.3),
  - `app.heat.pump.out` = `{run, active, heat_off, load, l_load,
    l_limit, l_buf, l_pump, t_cur, scaled_low, cop, reason}`,
  - `sensor.cop` (COP estimate, rate-limited),
  - feedback: `feedback.wp` (effective enable), `feedback.ice`.
- **State**: `{run, t_change, t_load, t_run, scaled_low, load_last,
  avg_heat, avg_heat_t, cop, pids: {load, buffer, limit}}`.

Core structure:

- `next_state(...)` is a pure function with an explicit transition
  table, including the legacy validity rules (only `+1` steps, any →
  `down`, `down` → `off`, `ice` → `wait_time`/`wait_flow`, `off` →
  `down` becomes `off`) and the restart rules (`orun is None`).
- Entry actions per state produce commands and flow requests
  (`enter_wait_flow`: mode off, `fixed` init PWM with `rate` preload,
  …). Per-state ticks implement the start conditions (`misc.start.*`,
  `misc.min_power`), the ice exit rules, the `down` exit rules, and in
  `run`: setpoints `t_limit`, `t_pump`, `t_buffer`, `t_load` (pellet
  variants when `pellet.out.t_pellet_on`), the `w` blend of
  `limit`/`buffer`, `scaled_low` decay and OFF rules 3/4/5/6/SCALED,
  the 30 s no-power rule.
- `pid.load` gains (Kd/Tf) follow `pellet.out.mode` (formerly changed
  by the pellet code).
- `t_change_max` exceeded → abnormal exit → emergency shutdown.
- `avg_heat`/`avg_heat_t` (used for the pellet-assisted start
  decision) belong to pump state only.
- Start permission comes from `selector.out.wp` and
  `override.wp != False`; `errors.out` non-empty blocks starting.
- `force_start` (legacy `--force-on`, kept for testing): skip the
  "buffer cold enough" test once, then clear the item. The CLI
  `moat dev heat pump --force-on` sets it.
- In passthru `original` state the unit writes nothing to `cmd.*` and
  stays in `off`.
- Dynamic load limit (new): the load is capped at an exponential
  average of the recent load (`load_limit.tau`, 10 min) plus
  `load_limit.margin` (0.25), but not below `load_limit.floor` (0.3),
  so the PIDs can't jump the compressor to
  full load; when the goal (`t_adj`) rises, the average is pushed up to
  at least `load_limit.push`. There is no outside-temperature start
  limit.
- The legacy "run the water pump when the heat pump's water is below
  `lim.defrost.temp`" rule in `off` never ran (its own transition rules
  turned `off` → `down` into `off`); it is not ported. Frost protection
  is a separate unit (moat-n84.29).

The adapter announces the pump service (§2.5), writes state
immediately on every transition, and on restart restores the load of
`run` from `load_last`.

As implemented (`PumpUnit`):

- Abnormal exits (§2.6) while the heat pump is not `off` run the
  emergency shutdown shielded, with `from_pump=True`, then re-raise:
  `errors.out` with severity `critical` while active (a warning only
  stops the heat pump the normal way), a stale sensor while active
  (`stale`, default 900 s without an update, for `stale_sensors`, default
  `t_in`, `t_out`, `r_flow`, `m_power`), a core timeout, any other
  exception, and cancellation. Afterwards the saved state is `off`
  without `load_last`, so a restart doesn't resume the run.
- Supplanted (e.g. by `moat dev heat off`): no shutdown of its own. As
  the supplant only shows up as a cancellation of the unit, the adapter
  then checks whether another client owns the pump service.
- `legacy_state` (default off) also writes the run state to a path, as
  the legacy code did to `heat.s.pump.state`.
- The shutdown on cancellation needs the Link client to stay up: a
  `Link` keeps its connection until its context is left, even when the
  enclosing scope is cancelled (moat-n84.32).
- `moat dev heat pump [--force-on]` runs the unit; `--force-on` sets
  `app.heat.force_start` first. Bypass is replaced by `override.wp`
  and passthru (decision 6).

### 3.5 `pellet` — pellet burner

Owns `p_load`, `p_buffer`.

- **Watches**: `sensor.pellet.state` (KWB state code),
  `sensor.buffer.{top,heat,mid,low}`, `sensor.temp.pellet`,
  `cmd.pellet.force` (`cm_pellet_force`), `target.out`,
  `selector.out`, `pump.out`, `app.heat.override.pellet`.
- **Publishes**: `cmd.pellet.load`, `cmd.pellet.temp`, the startup
  patch goals (`adj.pellet.startup.patch.path`), `app.heat.pellet.out`
  = `{t_pellet_on, pellet_on, load, hot, mode, state_code}`.
- **State**: `{t_pellet_on, pellet_on, load, pids: {p_load, p_buffer}}`.

Port of `run_set_pellet` plus the pellet writes from `run_pump`:

- State-code classification (off codes 0,1,3,5–9,21–35,≥43; running
  = 4; cleaning = 2 keeps the previous mode; starting otherwise); tri-state `t_pellet_on`: `False` (off),
  start timestamp (starting / running < `lim.pellet.t_min`), `True`
  (settled). `hot` tells the selector the burner can take over.
- Load branches: `force` input, preload when far below setpoint,
  full load while the heat pump runs, normal `min(p_load, blend)`;
  load 1 in codes 31/32.
- `cmd.pellet.temp` = `max(lim.pellet.temp.min, tp_limit)` and the
  startup-patch goals (startup value until running, `stop` value
  afterwards) — formerly written in `run_pump`.
- Edges of `selector.out.pellet`: on switch-on `move_to` for both PIDs
  (formerly done by the selector); on switch-off reset `t_pellet_on`
  and load.
- `mode` in `pellet.out` tells the pump which `pid.load` gains to use.
- Does **not** write `cmd.pellet.wanted`.

As implemented (`pellet.py`):

- `mode` is `off`, `starting` or `running` (code 4). Cleaning (code 2)
  happens while starting or running and leaves the mode as it was; after
  a restart that mode is taken from the saved state. The load is
  controlled only while `running`. Until the burner reports code 4
  (`pellet_on`), the unit asks for load 1 and the start-up temperature
  (`startup.buf` above the warmer buffer sensor, also written to the patch
  goals). That is where the legacy "load 1 in codes 31/32" comes from:
  the check inside `run_set_pellet` is dead code, as 31/32 are off codes.
- `t_pellet_on` holds wall-clock time, so a restart keeps the start time.
  As in the legacy code, code 4 right after `off` counts as settled at
  once (`time - False`).
- The burner is wanted when `override.pellet` says so, else when
  `selector.out.pellet` does. `override.pellet = False` also sets the load
  to 0, since this unit can't switch the burner off itself.
- `hot`: the burner runs and `sensor.temp.pellet` is at least `t_adj`
  (plus `hot_delta`).
- `tp_limit` is computed here from `target.out.demand` and the buffer
  sensors, as `run_pump` did.

### 3.6 `selector` — heat-source selection

Decides which heat sources run, including handover and fallback. A
single boolean is not sufficient: e.g. on a switch from heat pump to
pellets, the heat pump has to keep running until the pellet burner is
hot enough to take over.

- **Watches**: `sensor.temp.{current,predict}`, `sensor.pellet.state`,
  `sensor.buffer.{top,heat,low}`, `cmd.heat`, `target.out`,
  `pump.out`, `pellet.out`, `errors.out`, `app.heat.override.{wp,pellet}`.
- **Publishes**:
  - `app.heat.selector.out` = `{wp: bool, pellet: bool, primary:
    "wp" | "pellet" | None, phase: "steady" | "wp_to_pellet" |
    "pellet_to_wp", since, reason}`,
  - `cmd.pellet.wanted` (sole writer), optional `feedback.pellet`.
- **State**: `{primary, phase, since}`.

Rules:

- Primary choice: port of `run_temp_thresh` (outside temperature and
  forecast thresholds with ±0.15 hysteresis, buffer vs. `t_nom`/`t_low`,
  `t_ext > misc.pellet.avg_off`), with a time-based debounce instead
  of "every 10th update".
- WP → pellet: request pellet; keep `wp` until `pellet.out.hot`
  (configurable criterion), then release the heat pump.
- Pellet → WP: request WP; keep `pellet` until `pump.out.run == run`
  for a configurable time, then release the burner.
- Fallback: if the requested source does not come up within a timeout
  or reports errors, keep or revert to the other source and report
  the reason.
- Overrides (§2.7) take precedence; both sources forced off → nothing
  runs, reported as such.
- Stale inputs latch the current decision.

As implemented (`selector.py`):

- `out` is `{wp, pellet, primary, phase, reason, failed}`; `failed`
  lists the sources that failed within the last `retry` seconds (default
  2 h), which the selector won't choose again on its own until then. The
  state is `{primary, phase, since, failed}`; timers restart after a
  restart.
- The primary choice needs `debounce` seconds (default 120) of agreement.
  Missing inputs latch it.
- `wp_to_pellet` ends when `pellet.out.hot`; the burner has failed if it
  isn't `running` after `start_timeout` (30 min), isn't hot after
  `hot_timeout` (1 h), or reports one of `fail_codes` (none by default,
  the KWB fault codes still have to be collected).
- `pellet_to_wp` ends after the heat pump has been in `run` for `stable`
  seconds (10 min), or has stayed `off` for `idle_release` (30 min) without
  errors: with a warm buffer it has no reason to start, and waiting for it
  would keep the burner on indefinitely. `errors.out` reporting errors
  fails the heat pump.
- In steady pellet operation a burner that doesn't run counts as failed
  only while `tb_heat` is below `t_low`: it pauses when the buffer is warm.
- A failed source makes the other one primary at once (steady, no
  handover), unless it is forced off.
- Overrides: `True` forces the source on, `False` off; `False` also makes
  the other one primary, and both `False` means nothing runs.

### 3.7 `errors` — error aggregator

Publish-only; does not stop anything itself.

- **Watches**: `sensor.error` subtree (`feed`), `app.heat.override.errors`,
  optionally the feed writer's service announcement (`source`).
- **Publishes**: `app.heat.errors.out` = `{errors: {path: code},
  severity: "none" | "warning" | "critical", since}`; `path` is relative
  to the feed (e.g. `:3`), `since` is the wall-clock time of the last
  severity change.
- **State**: `{severity, since}`.
- Config: ignore list, default code 30055 (communication error) and
  path `:1`; per-code severity (default `critical`). A code of 0 means
  "no error".
- A stale feed is reported as a synthetic critical error `{stale:
  "stale"}`. Error codes are published on change, so their age says
  nothing; the feed counts as stale while the `source` announcement is
  not up. Without a `source`, staleness is not detected.
- The override item injects errors as `{value: {key: code}, expires,
  reason}`; the mapping must be wrapped in `value`.

### 3.8 `watchdog` (optional)

Handles the case where the pump unit cannot run its own shutdown
(hard kill, OOM, host crash).

- **Watches**: pump service liveness (`ServiceMonitor`),
  `app.heat.pump.out`, `app.heat.passthru.state`, its own disable item
  `app.heat.watchdog.disable` (`bool`).
- **Acts**: when the pump service is gone and the last `pump.out.run`
  is active (anything but `off`/`down`), runs
  `emergency_shutdown(from_pump=False)`. Inactive while disabled or
  in passthru `original`.
- **Publishes**: `app.heat.watchdog.out` = `{triggered_at, reason,
  duration, exit_delta}` for auditing.
- Never restarts the pump unit; that is up to systemd or the operator.

As implemented (`watchdog.py`):

- The pump service must have been gone for `grace` seconds (default 5):
  the pump unit's announcement and its first output are separate
  messages. A crashed pump unit's announcement disappears as soon as the
  link's service monitor sees its WILL.
- The pump unit's saved state is checked, too: after its own emergency
  shutdown it says `off` while `pump.out` may still show the last state.
- It fires once per pump run and is re-armed by new pump output, so its
  own takeover of the pump service doesn't trigger it again.
- `app.heat.watchdog.disable` is read like an override item (plain value
  or `{value, expires, reason}`).
- `out` is `{status, triggered_at, reason, result, duration,
  exit_delta}`, `status` being `watching`, `idle`, `disabled`,
  `passthru`, `shutdown` or `done`; the last intervention is also kept in
  the unit's state. `exit_delta` is `t_out - t_in` afterwards.
- The unit adapter runs the procedure: a core may ask its adapter to do
  something (`Step.act`, `Unit.act`).

### 3.9 `passthru`

See §2.8.

### 3.10 Ported daemons

- `pwm.py`: software PWM for `output.*` on RPi.GPIO (lazy import),
  now reading value and override paths from MoaT-Link.
  It announces the service `heat.pwm` (`run.host.<host>.heat.pwm`)
  while it drives its outputs, and withdraws it when it ends. The pump
  unit watches it: once it has been gone for `pump.pwm_grace` seconds
  (default 3) the heat pump is not started (reason `pwm`), and an
  active heat pump is stopped with the emergency shutdown (§2.6).
- `modbus_mon.py`: restarts `moat modbus dev poll` when the Solvis
  reports error code 26, now watching MoaT-Link.

### 3.11 `frost` — heat-pump loop frost protection

Port of the standalone `wp.py` task. Owns the heat-pump loop valve
(`home.ass.dyn.switch.plug-n5.relay.cmd`).

- **Watches**: `sensor.pump.{in,out}`, `app.heat.flow.out`, the valve's
  `.state`.
- **Publishes**: the valve command, `app.heat.frost.out` = `{active,
  pulse, t_min, reason}`.
- **State**: none; after a restart a loop below `t_start` starts a cycle.

When `min(t_in, t_out)` drops below `t_start` (8 °C) and nobody runs the
circulation pump, a cycle opens the valve and asks for `pulse` (1/16)
for `t_pulse` (5 s), then pauses for `t_wait` (60 s), until the loop is
at `t_stop` (10 °C). It ends early when the valve is closed by someone
else (after it has reported open), or when someone else runs the pump:
then the valve stays open for them. Otherwise the valve is open exactly
while `flow.out.pwm > 0` from something other than a pulse.

The pulses go through the flow unit (`app.heat.frost.out.pulse`), so
the flow unit stays the only writer of the PWM output and any request
or override takes precedence. The legacy task only noticed a PWM other
than its own at the end of a pulse; here the pump unit's request
replaces a pulse at once.

## 4. Migration and cutover

### 4.1 Data migration (`moat dev heat migrate`)

1. Read the production YAML (the `-c` file layered over the legacy
   `CFG` literal) and the legacy state (KV path or file).
2. Map every key through an explicit table `_CFG_MAP: old path →
   (unit, new path)`; unmapped non-deprecated keys are an error.
   Production keys not in the literal must be covered too:
   `pid.*.log.{value,setpoint}`, `setting.passthru`,
   `cmd.pellet.switch`, `lim.flow.min`, `state` as a Link path.
   Deprecated: `cmd.bypass.*` (→ overrides / passthru), `cmd.passthru`,
   `feedback.passthru`, `feedback.bypass`, `sensor.pump.state`.
3. Split the state: `p_flow`, `p_pump` → `flow`; `p_load`, `p_buffer`,
   `p_limit`, `run`, `t_change`, `t_run`, `t_load`, `scaled_low`,
   `load_last`, `avg_heat`, `avg_heat_t` → `pump`; `pp_load`,
   `pp_buffer`, `t_pellet_on`, `pellet_on`, `pellet_load` → `pellet`;
   `heat_ok` → `heat_valve`; `last_pwm`, `last_load`, `start_p` are
   dropped. PID timestamps are re-based to wall-clock time.
4. `--dry-run` prints a diff and a YAML dump; `--commit` writes the
   `cfg.app.heat.*` and `app.heat.*.state` items. Every result must
   validate against the unit's config model.

The script works on the YAML directly and does not import `solvis.py`.

As implemented (`system/migrate.py`, command in `migrate.py`):

- The legacy `CFG` literal is kept as `system/legacy.yaml`.
- One legacy key may feed several units (e.g. `sensor.pump.out`: pump,
  flow, heat_valve, frost, watchdog, emergency); `pid.load` also sets the
  pump's `load_pellet`, whose `d`/`tf` come from `adj.pellet.pid.load`.
  Dropped keys (with the reason) are listed by `-v`.
- Only values that differ from the package defaults are written. The
  production configuration maps to no changes at all: the package
  defaults are its values.
- State: the legacy `t_change`, `t_run` and `t_load` are wall-clock
  time, which is how the units persist their timestamps (`pid.MonoTime`);
  PID timestamps are set to the migration time; a pending `heat_ok`
  (a timestamp) becomes a pending switch-on that waits again.
- The state is read from `-s FILE`, else from where the config's `state`
  says (a Link path or a file). Without `--commit` the command prints the
  differences to the current Link items (`+` new, `~` changed) and the
  items as YAML.

### 4.2 Cutover

1. All units are implemented and tested against the simulator and the
   legacy reference traces (§5) while `solvis.py` stays untouched.
2. During a maintenance window: stop the legacy controller (heat pump
   idle), run `migrate --commit`, start the new units.
3. Delete `solvis.py`; wire all subcommands in `_main.py`.
4. Packaging (`packaging/moat-dev-heat/pyproject.toml`): drop
   `aionotify`; add `moat-link`, `moat-lib-config`, `pydantic`; bump
   `moat-util`, `moat-lib-pid`, `moat-lib-run`; `requires-python =
   ">=3.13"`; real description. Add the modules to
   `tool.ty.src.include` in the **root** `pyproject.toml`. Major version
   bump via `./mt src tag -s moat.dev.heat -M`.
5. Update `README.md` and `docs/moat-dev-heat/` (including the flow
   unit dependency of emergency shutdown).

### 4.3 Removed or changed features

- File-watched config reload (`aionotify`): replaced by §2.4.
- `--no-save`: dropped. `--force-on`: kept as `app.heat.force_start`.
- Bypass mode: replaced by overrides (§2.7) and passthru (§2.8).
- `record` / `replay` of `Data.__dict__`: replaced by the side-car
  recorder with open-loop replay into a test server, plus a converter
  for old recordings (`moat dev heat record save|replay|convert-legacy`,
  `record.py`; the timeline format is described there). Controller
  validation uses the closed-loop simulator.
- `pwm` and `modbus-monitor`: ported to MoaT-Link (§3.10).

## 5. Testing

### 5.1 Strategy

Open-loop replay of recordings cannot validate a controller whose
actions differ from the recorded ones: the recorded plant reacted to
the old controller's outputs. Testing therefore rests on three layers:

1. **Core tests** — table-driven and sequence tests of each sans-IO
   core, no I/O, simulated time.
2. **Closed-loop tests** — unit cores wired together in-process
   against the plant simulator, simulated time, fast and deterministic.
   Scenario outcomes are compared with **legacy reference traces**:
   the legacy `Data` class driven by the same simulator (through a
   fake KV client and `Data.TS`) before `solvis.py` is deleted.
3. **Link tests** — adapters and wiring against a real ephemeral
   MoaT-Link server (`moat.link._test.Scaffold`), real time with short
   timeouts, including an end-to-end run of all units plus the
   simulator's Link adapter.

### 5.2 Time

Cores never read a clock. They receive `now` (monotonic seconds) and
return the delay until they next need to be woken; inputs that depend on
the date (the target schedule) are passed in by the adapter. PIDs are
always called with an explicit `t`.

There is no clock object. Adapters use the event loop's time
(`anyio.current_time()`, `sleep_until()`, `move_on_after()`), which tests
replace with trio's `MockClock`. Wall-clock time, needed only for
persisted PID timestamps, override expiry and comparison with MoaT-Link
message timestamps, comes from `moat.util.time.time()`; tests patch it to
advance together with the mock clock. Closed-loop tests of the cores need
neither: they call `core.step()` and `sim.step()` in a plain loop.
Scaffold tests use real time (MoaT-Link message timestamps are
wall-clock).

### 5.3 Plant simulator

`moat.dev.heat.sim`: a deterministic (seeded), sans-IO physical model
advanced by `step(dt)`:

- stratified buffer (N layers, mixing, losses) with sensor taps for
  `tb_water`, `tb_heat`, `tb_mid`, `tb_low`, and the hot-water section;
- heat pump: output = load × Pmax(t_air) with a COP curve, `t_out =
  t_in + P / (c · flow)`, start delay, minimum load, power draw,
  compressor speed, de-ice cycles, over-temperature trip, error codes;
- circulation pump: flow(PWM) with dead zone and lag;
- heating circuit: radiator demand from outside temperature, valve
  modes, return temperature; switchover valve (`m_switch`);
- hot-water draw events;
- pellet boiler: KWB state-code sequence, ignition time and warm-up,
  ignition failure, load → power, top temperature;
- weather: outside temperature profile and forecast;
- fault injection: stuck or stale sensors, dead flow pump.

`moat dev heat sim` publishes the simulator on the real (or a test)
MoaT-Link tree with a configurable time scale, for end-to-end tests and
operator dry runs.

### 5.4 Test files

```
tests/moat_dev_heat/
    conftest.py           # heat_scaffold / heat fixtures, trace_check
    legacy.py             # legacy solvis.Data vs. simulator (reference traces)
    test_harness.py       # self-tests of runner, fixtures, trace compare
    test_legacy.py
    data/                 # legacy reference traces, scenario files
    test_sim.py           # simulator physics sanity
    test_link_helpers.py  # Reader, Writer, override readers, service monitor
    test_config.py        # combine_dict loader, live reload, invalid update, deletion
    test_state.py         # debounced/immediate save, restore
    test_pid.py           # APID wall-clock persistence, re-basing, logging
    test_target.py
    test_heat_valve.py
    test_flow.py
    test_pump_states.py   # transition table, entry actions, OFF rules, timeouts
    test_pump_unit.py     # adapter: abnormal exits, supplant, force_start, override
    test_pellet.py
    test_selector.py      # decision matrix, handover, fallback, overrides
    test_errors.py
    test_emergency.py
    test_watchdog.py
    test_passthru.py
    test_pwm.py           # fake GPIO
    test_migrate.py
    test_closed_loop.py   # core-only scenarios vs. legacy reference traces
    test_integration.py   # all units + simulator on Scaffold
    test_restart.py
```

Per-unit acceptance criteria are recorded in the Beads issues. Common
safety invariants, asserted in every closed-loop and end-to-end
scenario:

- the heat pump never has load while flow is zero,
- `t_out` stays below the trip temperature,
- PWM is > 0 whenever `t_out - t_in > stop_delta`,
- no output is written by the pump unit while passthru is `original`.

Scenarios: cold start / warm-up, steady state, de-ice, WP → pellet and
pellet → WP handover (no buffer dip below `t_low`), pellet ignition
failure → fallback, day/night switch, error mid-run → emergency
shutdown, stale sensor, flow unit dead during emergency (documented
residual risk), pump restart mid-run with and without watchdog, each
override with expiry, passthru requested while the heat pump runs
(deferred until idle), force start.

Reference traces are refreshed only via an explicit pytest option
(`--heat-refresh`); a missing reference fails;
comparison diffs go to a temporary file.

## 6. Implementation order

Each step is a self-contained commit with its tests. See the Beads
epic for dependencies.

1. `moat.lib.config.base.BaseModel` extensions.
2. Verify all sensor/command paths in MoaT-Link.
3. Package skeleton and shared infrastructure (§2.1–2.4, APID).
4. Plant simulator core; legacy reference traces; test harness;
   simulator Link adapter.
5. Override items.
6. `target`, `flow`, `errors`.
7. `heat_valve`, `pellet`, `selector`.
8. `pump` core, `emergency`, `pump` adapter, `watchdog`.
9. `moat.modbus` RPC service and switchable forwarding; `passthru`.
10. Ported daemons, recorder, `system/runner.py`, end-to-end scenarios.
11. `migrate`; cutover (§4.2).

## 7. Risks and open questions

- **PID cadence.** The legacy PIDs tick on *any* input change. The new
  units tick on their own inputs plus a timer. Gains may need retuning;
  the closed-loop comparison with the legacy traces shows how much.
- **Restart bumpiness.** Integrators are restored from state
  (wall-clock timestamps, re-based after long outages). The flow unit
  uses `move_to` on its first tick after a restart.
- **Flow unit dead during emergency.** See §2.6.
- **Inter-unit latency.** Inputs such as `flow.out.pwm` now arrive via
  MQTT. They do not feed PIDs directly, so latency in the 10–100 ms
  range is harmless; verified in the end-to-end tests.
- **Conflicting operator writes.** Overrides are last-writer-wins; the
  `reason` and `expires` fields let a UI show who set what.
- **Schema validation.** Schemas for `cfg.app.heat.*`, `app.heat.*.out`
  and the override items are published so that malformed writes are
  rejected at the source.
- **Passthru open items.** See §2.8.
