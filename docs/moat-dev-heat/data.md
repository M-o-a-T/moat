(moat-dev-heat-data)=
# Heat-controller data in MoaT-Link

Every MoaT-Link item the heat controller (moat.dev.heat, epic moat-n84)
reads or writes, and who writes it. The structure of each item is in
{download}`schema.yaml <schema.yaml>`; the production survey with
update rates and known gaps is in
[`moat/dev/heat/PATHS.md`](https://github.com/M-o-a-T/moat/blob/main/moat/dev/heat/PATHS.md).

Conventions:

- **Retained.** Everything below is retained; a restarting unit receives
  the last value of every input at once.
- **Ownership.** Each unit is the sole writer of its `out` and `state`
  items (`moat dev heat migrate` seeds the latter once). Sensor readings
  under `heat.s.*` and `temp.*` come from the Modbus pollers and bridging
  jobs; the units write commands (`*.cmd`), PID logs and the water-pump
  PWM there, as listed below.
- **Wildcards.** `+` matches one path element, `#` one or more.

Units: `target` (heating curve, demand), `heat_valve` (heating circuit),
`flow` (water-pump PWM), `pump` (heat pump), `pellet` (pellet burner),
`selector` (which source runs), `errors` (aggregation), `frost` (loop
frost protection), `watchdog` (crash cover), `passthru` (maintenance
handover to the original controller). Support processes: `pwm` (software PWM daemon),
`modbus_mon` (Solvis poller babysitter), `run` (system runner).

## Unit coordination (`app.heat.*`)

| Path | Writer | Description |
| --- | --- | --- |
| `app.heat.target.out` | target | Heating curve and buffer demand: flow temperature (computed and effective), day/night, outside temperature, demand setpoints. |
| `app.heat.heat_valve.out` | heat_valve | Heating circuit state: on, pending, reason code. |
| `app.heat.flow.out` | flow | Water pump: PWM, control mode, stability, applied request seq. |
| `app.heat.pump.out` | pump | Heat pump: run state, active, load, PID outputs, COP, reason. |
| `app.heat.pellet.out` | pellet | Pellet burner: settled/hot, load, classified mode, KWB code. |
| `app.heat.selector.out` | selector | Which sources may run, primary, handover phase, failures. |
| `app.heat.errors.out` | errors | Aggregated heat-pump errors and their severity. |
| `app.heat.frost.out` | frost | Frost cycle: active, current pulse, loop minimum temperature. |
| `app.heat.watchdog.out` | watchdog | Status, and a record of the last emergency shutdown. |
| `app.heat.flow.request` | pump, emergency shutdown | What the water pump should do (mode, rate, temp, PWM bounds, seq). |
| `app.heat.force_start` | operator (CLI `--force-on`), pump | One-shot "start although the buffer is warm"; pump sets it to null when consumed. |
| `app.heat.passthru.request` | HA job, passthru (reset) | Hand the heat pump to its original controller (passthru), or take it back. |
| `app.heat.passthru.state` | passthru | `{bypass, switching}`: whether the original controller is in charge, and what a switch waits for. Read by pump, watchdog and the Modbus bypasses. |
| `app.heat.watchdog.disable` | operator | Disable the watchdog; plain bool or `{value, expires, reason}`. |

## Operator overrides (`app.heat.override.*`)

Absent or null = automatic; `{value, expires, reason}` lapses at
`expires`, and the units reading it then delete the item.
`moat dev heat override --schemas` publishes the items' schemas at
`schema.app.heat.override.NAME`, so that malformed writes are rejected.
Set with `moat dev heat override` (all but `errors`).

| Path | Writer | Description |
| --- | --- | --- |
| `app.heat.override.wp` | operator | Heat pump forced on (true) / off (false) / automatic. |
| `app.heat.override.pellet` | operator | Pellet burner forced on / off / automatic. |
| `app.heat.override.flow_temp` | operator | Flow temperature instead of the heating curve. °C. |
| `app.heat.override.pwm` | operator | Water-pump PWM instead of the flow unit's. 0…1. |
| `app.heat.override.errors` | operator | Errors injected into the errors unit, by key. |

## Persistent state (`app.heat.<unit>.state`)

Written by the owning unit (debounced, immediate on critical changes),
and once by `moat dev heat migrate`. Timestamps are wall-clock time, so they survive a reboot.

| Path | Writer | Description |
| --- | --- | --- |
| `app.heat.target.state` | target | Force-switch locks (day, night). |
| `app.heat.heat_valve.state` | heat_valve | Circuit on; ok-since while the switch-on delay runs. |
| `app.heat.flow.state` | flow | Both PIDs' state, last PWM, applied request seq. |
| `app.heat.pump.state` | pump | Run state, phase timers, scaled-low, COP, load-average, three PIDs. |
| `app.heat.pellet.state` | pellet | Burner settled/seen-running, load, two PIDs. |
| `app.heat.selector.state` | selector | Primary, phase, since, failed sources. |
| `app.heat.errors.state` | errors | Published severity and when it changed. |
| `app.heat.watchdog.state` | watchdog | Record of the last intervention. |

## Configuration (`cfg.app.heat.*`)

Package defaults (`moat/dev/heat/_cfg.yaml`) merged with the Link item,
the latter winning. Live-reloaded; invalid updates are ignored, deletion
reverts to the defaults. Written by `moat dev heat migrate` and
operators.

| Path | Writer | Description |
| --- | --- | --- |
| `cfg.app.heat.<unit>` | operator, migrate | One configuration item per unit. |
| `cfg.app.heat.service` | operator, migrate | Shared: announcement host name, restart backoff, recovery. |
| `cfg.app.heat.emergency` | operator, migrate | Tunables of the emergency shutdown (rates, timeouts, paths). |
| `cfg.app.heat.pwm` | operator, migrate | PWM daemon: GPIO pins, value paths, frequencies. |
| `cfg.app.heat.modbus_mon` | operator | Solvis monitor: error path, poller config, timings. |
| `cfg.app.heat.passthru` | operator | Passthru: idle threshold, and `errors`, the error subtrees that end a bypass (the Solvis host's poll errors, the Solvis poller's service). |

## Home-Assistant bridge (`app.heat.ha.*`)

The units never touch HA entities; jobs on the main node copy between
these and `home.ass.dyn` (see `examples/moat-dev-heat/HA.md`).

| Path | Writer | Description |
| --- | --- | --- |
| `app.heat.ha.heat` | HA job | Heating enabled (copy of the `heizung.main` switch). |
| `app.heat.ha.heat_state` | heat_valve | Echo of heating enabled. |
| `app.heat.ha.force_day.cmd` | HA job, target | Force day (the `day_mode` switch); target turns it off when force night is turned on. |
| `app.heat.ha.force_day.state` | target | Force-day feedback; turning one on clears the other. |
| `app.heat.ha.force_night.cmd` | HA job, target | Force night (the `night_mode` switch); target turns it off when force day is turned on. |
| `app.heat.ha.force_night.state` | target | Force-night feedback. |
| `app.heat.ha.t_air` | HA job, simulator | Current outside temperature for the selector. °C. |
| `app.heat.ha.pump_state` | heat_valve | Heating-circuit pump runs. |
| `app.heat.ha.wp_enabled` | pump | Heat pump effectively enabled (the wp override job's "actual"). |
| `app.heat.ha.de_ice` | pump | Heat pump de-ices. |
| `app.heat.ha.cop` | pump | COP estimate, rate-limited. |
| `app.heat.ha.valve.cmd` | frost | Heat-pump loop valve (smart plug). |
| `app.heat.ha.valve.state` | HA job | Loop-valve feedback. |

## Heat pump (`heat.s.pump.*`)

Polled from the Stiebel heat pump by the Modbus poller
(`modbus.stiebel.yaml`), except where noted.

| Path | Writer | Description |
| --- | --- | --- |
| `heat.s.pump.temp.in` | poller | Loop inflow temperature. °C. |
| `heat.s.pump.temp.out` | poller | Loop outflow temperature. °C. |
| `heat.s.pump.flow` | poller | Loop flow rate. l/min. |
| `heat.s.pump.de_ice` | poller | The heat pump is de-icing. |
| `heat.s.pump.power` | poller | Electrical power draw. kW. |
| `heat.s.pump.state` | poller | The heat pump's own state code. |
| `heat.s.pump.switchover` | poller (Solvis) | The heat pump feeds the water buffer, not the heating. |
| `heat.s.pump.err:N` | poller | Error slot N's code; 0 = no error. |
| `heat.s.pump.cmd.power` | pump, emergency | Commanded load, 0…1; forwarded to the heat pump. |
| `heat.s.pump.cmd.mode` | pump, emergency | Operating mode (3 on, 0 off); forwarded. |
| `heat.s.pump.cmd.want.mode` | stiebelfake | The mode the original controller asks for (used in passthru). |
| `heat.s.pump.cmd.want.power` | stiebelfake | The load the original controller asks for (used in passthru). |
| `heat.s.pump.cmd.live` | stiebelfake | Keepalive between the Solvis emulation and the poller. |
| `heat.s.pump.cmd.reset` | stiebelfake | Reset handshake between the emulation and the poller. |
| `heat.s.pump.pid` | flow | Circulation-pump PWM, 0…1; output by the `pwm` daemon. |
| `heat.s.pump.rate.cmd` | poller (Solvis) | The Solvis' circulation-pump output (PWM 0…1), polled every second; followed while bypassed. |
| `heat.s.pump.compr.speed` | poller | Compressor speed; 0 = off. |
| `heat.s.pump.pct.NAME` | flow, pump | PID output logs (flow, pump, load, buffer, limit). |
| `heat.s.pump.set.NAME` | flow, pump | PID setpoint logs. |
| `heat.s.pump._c:N`, `_x:N`, `_y:N` | poller | Raw diagnostic registers. |

## Buffer and heating circuit (`heat.s.buffer.*`, `heat.s.heat.*`, `heat.s.water.*`)

Polled from the Solvis controller (`modbus.heat.yaml`, host `wp`):
the buffer and circuit sensors, and read-backs of the setpoints and
modes that the `*.cmd` items set.

| Path | Writer | Description |
| --- | --- | --- |
| `heat.s.buffer.temp.water` | poller | Water-buffer top. °C. |
| `heat.s.buffer.temp.heat` | poller | Heating-buffer top. °C. |
| `heat.s.buffer.temp.mid` | poller | Buffer middle. °C. |
| `heat.s.buffer.temp.return` | poller | Buffer bottom (return). °C. |
| `heat.s.buffer.temp.switch` | poller | Mixing/switchover zone. °C. |
| `heat.s.heat.temp` | poller (Solvis echo) | Read-back of `heat.temp.cmd`: the Solvis' fixed day flow temperature. Basis of the demand values. °C. |
| `heat.s.heat.temp_low(.cmd)` | poller / operator | Reduced (night) flow temperature, read back and commanded. °C. |
| `heat.s.heat.temp.cmd` | target | Flow temperature for the Solvis (curve value + 0.8, truncated). |
| `heat.s.heat.mode` | poller (Solvis echo) | Heating-circuit mode. |
| `heat.s.heat.mode.cmd` | heat_valve | Heating circuit on (3) / standby (5); forwarded. |
| `heat.s.heating.temp.out` | poller | Heating-circuit outflow. °C. |
| `heat.s.water.temp` | poller (Solvis echo) | Hot-water setpoint. °C. |
| `heat.s.water.temp.cmd` | operator | Hot-water setpoint; forwarded to the Solvis. |
| `heat.s.water.mode(.cmd)` | poller / operator | Hot-water mode and its command. |

## Heating-circuit pump (`heat.s.heating.pump.*`)

Polled from the Wilo-Para MAXO circulation pump (`modbus.wilo.yaml`;
moat-565). Its speed setpoint replaces the legacy GPIO heat pin: the
`envelope` job derives it from the target-vs-actual flow-temperature
difference, and the poller forwards it to the pump together with the
heat valve's on/off state. Quasi-static settings (control function,
fallback presets, bus-command timer) are held by the poller as consts
and rewritten every minute, so a lost frame can't corrupt them; when
the bus-command timer expires the pump falls back to its presets
(30 % duty, on).

| Path | Writer | Description |
| --- | --- | --- |
| `heat.s.heating.pump.cmd.duty` | envelope | Speed setpoint. %. |
| `heat.s.heating.pump.duty` | poller | Duty-point setpoint, read back. %. |
| `heat.s.heating.pump.duty_actual` | poller | Actual duty point. %. |
| `heat.s.heating.pump.duty_max`, `.duty_min` | poller | Allowed duty-point range. %. |
| `heat.s.heating.pump.duty_100` | poller | Physical value at 100 % duty (mode-dependent). |
| `heat.s.heating.pump.duty_units` | poller | Unit of that physical value (rpm, W, m³/h, …). |
| `heat.s.heating.pump.speed` | poller | Pump speed. rpm. |
| `heat.s.heating.pump.flow` | poller | Calculated flow rate. m³/h; 65535 = no data. |
| `heat.s.heating.pump.pressure` | poller | Differential pressure. cmH₂O. |
| `heat.s.heating.pump.power` | poller | Power consumption. W. |
| `heat.s.heating.pump.energy` | poller | Energy consumption. kWh. |
| `heat.s.heating.pump.op_time` | poller | Operating hours. h. |
| `heat.s.heating.pump.control_function` | poller | Control mode (n_const, dp_const, dp_var). |
| `heat.s.heating.pump.active` | poller | The pump is running. |
| `heat.s.heating.pump.status` | poller | Status bitmap (ready, running, warning, error, final). |
| `heat.s.heating.pump.error` | poller | Warning/error code; 0 = none. |
| `heat.s.heating.pump.timer_left` | poller | Remaining bus-command-timer time. s. |
| `heat.s.heating.pump.heartbeat` | poller | Interface heartbeat counter. |

## Pellet burner (`heat.s.pellets.*`)

Polled from the KWB burner (`modbus.heat.yaml`).

| Path | Writer | Description |
| --- | --- | --- |
| `heat.s.pellets.state` | poller | KWB state code (off: 0,1,3,5–9,21–35,≥43; 4 running; 2 cleaning, mode unchanged; else starting). |
| `heat.s.pellets.temp.top` | poller | Burner top temperature. °C. |
| `heat.s.pellets.temp.goal(.cmd)` | poller / pellet | Temperature goal, read back and commanded. °C. |
| `heat.s.pellets.load` | poller | Actual burner load. 0…1. |
| `heat.s.pellets.load.goal(.cmd)` | poller / pellet | Load goal, read back and commanded. 0…1. |
| `heat.s.pellets.load.force` | operator | Use this load instead of the controller's. 0…1, absent = auto. |
| `heat.s.pellets.power` | poller | Burner request flag, read back. |
| `heat.s.pellets.power.cmd` | cutover job | Burner request, forwarded by the poller; derived from `.auto` (moat-n84.24). |
| `heat.s.pellets.power.cmd.auto` | selector | Whether the burner should run; sole writer. |
| `heat.s.pellets.aux:1.goal`, `aux:2.goal`, `aux.r-min.goal` | pellet | Start-up temperature patched into the burner's controller. |
| `heat.s.pellets.aux:1`, `aux:2`, `aux.r-min` | poller | Those goals' read-backs. |
| `heat.s.pellets.pct.NAME` | pellet | PID output logs (load, buffer). |
| `heat.s.pellets.set.NAME` | pellet | PID setpoint logs. |
| `heat.s.pellets.storage`, `.energy`, `.used`, `.prog`, `.exhaust`, … | poller | Consumption and diagnostics. |

## Solvis controller (`heat.s.control.*`)

| Path | Writer | Description |
| --- | --- | --- |
| `heat.s.control.errors` | poller | Number of errors the Solvis reports. |
| `heat.s.control.errors:N.code|.time|.p1|.p2` | poller | Solvis error slots; code 26 makes modbus_mon restart the poller. |

## Environment (`temp.*`)

| Path | Writer | Description |
| --- | --- | --- |
| `temp.avg.temp.aussen_kompost.min` | aggregation (main node) | Smoothed outside temperature for the curve; gated to the heating host. °C. |
| `temp.min.forecast:N` | weather.min-temp job | Forecast minimum over the next N hours (4…24); the selector reads N=6. °C. |

## Services, errors, schemas

| Path | Writer | Description |
| --- | --- | --- |
| `run.host.<host>.heat.<unit>` | each unit, pwm daemon | Service announcement/liveness; `<host>` is the configured installation-wide name (default `heat`). |
| `error.app.heat.<unit>` | run (system runner) | A unit failed; cleared after it runs again for `recovery` seconds. |
| `schema.app.heat.override.NAME` | `override --schemas` | JSON schema of each override item, so writes are checked. |

## Optional paths

These are off (`None`) by default and only used when configured.

| Setting | Unit | Description |
| --- | --- | --- |
| `cfg.app.heat.heat_valve.pin` | heat_valve | Heating circuit on (1.0) / off (0.0), for a `pwm` daemon output. |
| `cfg.app.heat.selector.feedback_pellet` | selector | Echo of the burner request. |
| `cfg.app.heat.pump.legacy_state` | pump | The run state as a number (legacy writer of `heat.s.pump.state`). |
| `cfg.app.heat.errors.source` | errors | Service announcement of the error feed's writer; while it's down, the feed counts as stale. |
| `cfg.app.heat.pwm.outputs.NAME.override` | pwm | `flag` and `val` paths: while the flag is true, output the value instead. |
