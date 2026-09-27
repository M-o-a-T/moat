# Heat controller I/O paths in MoaT-Link

Inventory of every sensor, command, setting, feedback and output path in
the legacy `solvis.py` configuration, and where it lives in MoaT-Link
(surveyed 2026-09-27 against the production server; see HEAT.md §2.2).

## Where the data comes from

| KV subtree | Link location | Gateway | Notes |
| --- | --- | --- | --- |
| `heat.*` | `legacy.heat.*` | `gate.kv.heat` | written into KV on `s-bed` (Modbus poller, PWM daemon, `solvis.py`) |
| `temp.*` | `legacy.temp.*` | `gate.kv.temp` | |
| `home.ass.*` | `home.ass.*` | `gate.kv.hass` and `gate.hass` (MQTT) | `.state` mostly via KV, `.cmd` via Home Assistant's MQTT |

`heat.s.*` and `temp.*` therefore do **not** keep their KV names in
Link: a unit reads them with the `legacy.` prefix. `home.ass.*` keeps
its name. A stale copy of `home.ass` also exists under
`legacy.home.ass`; do not use it.

Values are published on change. While the heat pump is idle, its sensors
(`heat.s.pump.*`) are not updated for weeks, so age is not a liveness
signal. Buffer and heating-circuit temperatures change several times a
minute while any heating runs.

## Paths

"Age" is the time since the last update when surveyed.
"2 min" is the number of updates seen in a two-minute window.

### Sensors

| Old CFG key | KV path | Link path | Type | Age | 2 min |
| --- | --- | --- | --- | --- | --- |
| `sensor.pump.in` | `heat.s.pump.temp.in` | `legacy.heat.s.pump.temp.in` | float | 62d | 0 |
| `sensor.pump.out` | `heat.s.pump.temp.out` | `legacy.heat.s.pump.temp.out` | float | 62d | 0 |
| `sensor.pump.flow` | `heat.s.pump.flow` | `legacy.heat.s.pump.flow` | float | 87d | 0 |
| `sensor.pump.ice` | `heat.s.pump.de_ice` | `legacy.heat.s.pump.de_ice` | bool | 87d | 0 |
| `sensor.pump.state` | `heat.s.pump.state` | `legacy.heat.s.pump.state` | int | 16d | 0 |
| `sensor.buffer.top` | `heat.s.buffer.temp.water` | `legacy.heat.s.buffer.temp.water` | float | 3m | 10 |
| `sensor.buffer.heat` | `heat.s.buffer.temp.heat` | `legacy.heat.s.buffer.temp.heat` | float | 3m | 9 |
| `sensor.buffer.mid` | `heat.s.buffer.temp.mid` | `legacy.heat.s.buffer.temp.mid` | float | 3m | 6 |
| `sensor.buffer.low` | `heat.s.buffer.temp.return` | `legacy.heat.s.buffer.temp.return` | float | 3m | 4 |
| `sensor.error` | `heat.s.pump.err` | `legacy.heat.s.pump.err:1` … `err:20` | subtree | | |
| `sensor.power` | `heat.s.pump.power` | `legacy.heat.s.pump.power` | float | 87d | 0 |
| `sensor.cop` | `home.ass.dyn.sensor.heizung.wp_cop.state` | same | float | 126d | 0 |
| `sensor.temp.current` | `temp.avg.temp.aussen_kompost` | `legacy.temp.avg.temp.aussen_kompost` | float | 97d | 0 |
| `sensor.temp.predict` | `temp.min.forecast:6` | `legacy.temp.min.forecast:6` | float | 220d | 0 |
| `sensor.temp.pellet` | `heat.s.pellets.temp.top` | `legacy.heat.s.pellets.temp.top` | float | 4m | 0 |
| `sensor.temp.heat` | `heat.s.heating.temp.out` | `legacy.heat.s.heating.temp.out` | float | 3m | 13 |
| `sensor.pellet.state` | `heat.s.pellets.state` | `legacy.heat.s.pellets.state` | int | 62d | 0 |
| `adj.curve.current` | `temp.avg.temp.aussen_kompost.min` | `legacy.temp.avg.temp.aussen_kompost.min` | float | 7m | 1 |
| `misc.switch.state` | `heat.s.pump.switchover` | `legacy.heat.s.pump.switchover` | bool | 51m | 0 |

### Settings

| Old CFG key | KV path | Link path | Type | Age |
| --- | --- | --- | --- | --- |
| `setting.heat.day` | `heat.s.heat.temp` | `legacy.heat.s.heat.temp` | int | 11m |
| `setting.heat.night` | `heat.s.heat.temp_low` | `legacy.heat.s.heat.temp_low` | int | 13d |
| `setting.heat.mode.path` | `heat.s.heat.mode.cmd` | `legacy.heat.s.heat.mode.cmd` | int | 39m |
| `setting.heat.mode.force.day.cmd` | `home.ass.dyn.switch.heizung.day_mode.cmd` | same | bool | 4d |
| `setting.heat.mode.force.day.state` | `home.ass.dyn.switch.heizung.day_mode.state` | same | bool | 4d |
| `setting.heat.mode.force.night.cmd` | `home.ass.dyn.switch.heizung.night_mode.cmd` | same | bool | 418d |
| `setting.heat.mode.force.night.state` | `home.ass.dyn.switch.heizung.night_mode.state` | same | bool | 16d |
| `setting.water` | `heat.s.water.temp` | `legacy.heat.s.water.temp` | int | 62d |
| `adj.curve.setting` | `heat.s.heat.temp.cmd` | `legacy.heat.s.heat.temp.cmd` | int | 12m |

### Commands and outputs

| Old CFG key | KV path | Link path | Type | Age |
| --- | --- | --- | --- | --- |
| `cmd.bypass.cmd` | `home.ass.dyn.switch.heizung.wp_bypass.cmd` | same | bool | 418d |
| `cmd.bypass.mode` | `heat.s.pump.cmd.want.mode` | `legacy.heat.s.pump.cmd.want.mode` | int | 85d |
| `cmd.bypass.power` | `heat.s.pump.cmd.want.power` | `legacy.heat.s.pump.cmd.want.power` | float | 85d |
| `cmd.flow` | `heat.s.pump.rate.cmd` | `legacy.heat.s.pump.rate.cmd` | float | 48m |
| `cmd.wp` | `home.ass.dyn.switch.heizung.wp.cmd` | same | bool | 126d |
| `cmd.heat` | `home.ass.dyn.switch.heizung.main.cmd` | same | bool | 1h |
| `cmd.mode.path` | `heat.s.pump.cmd.mode` | `legacy.heat.s.pump.cmd.mode` | int | 16d |
| `cmd.power` | `heat.s.pump.cmd.power` | `legacy.heat.s.pump.cmd.power` | int | 16d |
| `cmd.pellet.force` | `heat.s.pellets.load.force` | `legacy.heat.s.pellets.load.force` | null | 431d |
| `cmd.pellet.temp` | `heat.s.pellets.temp.goal.cmd` | `legacy.heat.s.pellets.temp.goal.cmd` | int | 62d |
| `cmd.pellet.load` | `heat.s.pellets.load.goal.cmd` | `legacy.heat.s.pellets.load.goal.cmd` | int | 62d |
| `cmd.pellet.wanted` | `heat.s.pellets.power.cmd.auto` | `legacy.heat.s.pellets.power.cmd.auto` | bool | 20h |
| `cmd.pellet.run` | `heat.s.pellets.power.cmd` | `legacy.heat.s.pellets.power.cmd` | bool | 55d |
| `cmd.passthru.pump` | `home.ass.dyn.switch.heizung.wp_auto_mode.cmd` | same | bool | 418d |
| `cmd.passthru.pellet` | `home.ass.dyn.switch.heizung.pellet_auto_mode.cmd` | same | bool | 418d |
| `adj.pellet.startup.patch.path` | `heat.s.pellets.aux:1.goal`, `aux:2.goal`, `aux.r-min.goal` | `legacy.` + KV path | float | 3m |
| `output.flow.path` | `heat.s.pump.pid` | `legacy.heat.s.pump.pid` | int | 87d |
| `output.flow.override.flag` | `home.ass.state.input_boolean.test_override_on.state` | same | bool | 418d |
| `output.flow.override.val` | `home.ass.state.input_number.test_override_pct.state` | same | float | 418d |

### Feedback (written by the controller, read by Home Assistant)

| Old CFG key | KV path | Link path | Type | Age |
| --- | --- | --- | --- | --- |
| `feedback.wp`, `feedback.main` | `home.ass.dyn.switch.heizung.wp.state` | same | bool | 16d |
| `feedback.bypass` | `home.ass.dyn.switch.heizung.wp_bypass.state` | same | bool | 418d |
| `feedback.heat` | `home.ass.dyn.switch.heizung.main.state` | same | bool | 1h |
| `feedback.pump` | `home.ass.dyn.binary_sensor.heizung.pump.state` | same | bool | 39m |
| `feedback.ice` | `home.ass.dyn.binary_sensor.heizung.wp_de_ice.state` | same | bool | 87d |
| `feedback.passthru.pump` | `home.ass.dyn.switch.heizung.wp_auto_mode.state` | missing; HA publishes `home.ass.state.switch.heizung_wp_auto_mode.state` | bool | |
| `feedback.passthru.pellet` | `home.ass.dyn.switch.heizung.pellet_auto_mode.state` | missing; HA publishes `home.ass.state.switch.heizung_pellet_auto_mode.state` | bool | |

## Gaps

- `temp.min.forecast:*` has not been updated for 220 days, and the
  `temp.avg.temp.aussen_kompost` node itself for 97 days (its `.min`
  child is current).
- `gate.hass.heat` (MQTT, JSON codec) fails to decode
  `heat.s.pump.err` and the `*_auto_mode` switch topics; see
  `error.link.mqtt.codec.hass.heat.*`.
