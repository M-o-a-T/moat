# Home Assistant and the heating

The heat units know nothing about Home Assistant. They read and write
`app.heat.ha.*` and the override items `app.heat.override.*`. MoaT-Link
jobs on the main node (s-bed, or any other job runner there) copy
between those and the HA entities in `home.ass.dyn`; the Link gateway
then carries `app.heat` to and from the heating host (see I3.md).

HA paths below are relative to `home.ass.dyn`.

## HA entities

Existing entities (their `….config` nodes are already there):

| Entity | Type |
| --- | --- |
| `switch.heizung.main` | switch: heating on/off |
| `switch.heizung.day_mode`, `switch.heizung.night_mode` | switches: force day / night |
| `switch.heizung.wp` | switch: heat pump |
| `switch.heizung.pellets` | switch: pellet burner |
| `binary_sensor.heizung.pump` | heating circuit pump runs |
| `binary_sensor.heizung.wp_de_ice` | heat pump de-ices |
| `sensor.heizung.wp_cop` | heat pump COP |
| `sensor.temp.garten_kompost_schatten` | outside temperature |
| `switch.plug-n5.relay` | the heat-pump loop valve (a smart plug) |

New entities for the overrides (`moat link ha set TYPE PATH …` creates
the `config` nodes):

```shell
moat link ha set switch heizung.wp_override -s name "Wärmepumpe manuell"
moat link ha set switch heizung.pellets_override -s name "Pellets manuell"
moat link ha set number heizung.flow_temp -s name "Vorlauf" -v min 20 -v max 75 -v step 0.5 -s unit °C
moat link ha set switch heizung.flow_temp_override -s name "Vorlauf manuell"
moat link ha set number heizung.pwm -s name "Umwälzpumpe" -v min 0 -v max 1 -v step 0.01
moat link ha set switch heizung.pwm_override -s name "Umwälzpumpe manuell"
```

They replace the `input_boolean.test_override_on` /
`input_number.test_override_pct` helpers, which the PWM daemon used to
read directly: the PWM override now goes through the flow unit
(`app.heat.override.pwm`).

## Copies

One `transform.copy.value` job per row (`src` → `dst`; check the
parameter names against the stored snippet).

| src | dst | For |
| --- | --- | --- |
| `switch.heizung.main.cmd` | `app.heat.ha.heat` | heating enabled (target, heat_valve, selector) |
| `app.heat.ha.heat_state` | `switch.heizung.main.state` | heat_valve's echo |
| `switch.heizung.day_mode.cmd` | `app.heat.ha.force_day.cmd` | target |
| `app.heat.ha.force_day.state` | `switch.heizung.day_mode.state` | target |
| `switch.heizung.night_mode.cmd` | `app.heat.ha.force_night.cmd` | target |
| `app.heat.ha.force_night.state` | `switch.heizung.night_mode.state` | target |
| `app.heat.ha.pump_state` | `binary_sensor.heizung.pump.state` | heat_valve |
| `app.heat.ha.de_ice` | `binary_sensor.heizung.wp_de_ice.state` | pump |
| `app.heat.ha.cop` | `sensor.heizung.wp_cop.state` | pump |
| `sensor.temp.garten_kompost_schatten.state` | `app.heat.ha.t_air` | selector |
| `app.heat.ha.valve.cmd` | `switch.plug-n5.relay.cmd` | frost |
| `switch.plug-n5.relay.state` | `app.heat.ha.valve.state` | frost |

When one force switch is turned on, the target unit turns the other one
off by writing its `app.heat.ha.force_*.cmd`; that isn't copied back, but
HA shows the switch's `.state`, which the target unit clears as well.

## Overrides

An override item (`app.heat.override.*`: a value, or unset for
"automatic") is shown in HA as two entities, handled by one
`transform.hass.override` job each (`../moat-link-job/code.transform.hass.override.yaml`):

- `value`: the on/off switch or number,
- `manual`: a switch that turns the override on.

`manual` on sets the override to `value`'s last command (or, if there
was none, to what the heating does now); a `value` command while
`manual` is on changes it; `manual` off clears it. While `manual` is
off, `value` shows the heating's `actual` state, so the switch follows
what the heating does. The override item is authoritative: if someone
else sets or clears it (`moat dev heat override`), HA follows.

| Job | `dst` | `value` | `manual` | `actual` | `key` |
| --- | --- | --- | --- | --- | --- |
| `heat.ovr.wp` | `app.heat.override.wp` | `…switch.heizung.wp` | `…switch.heizung.wp_override` | `app.heat.ha.wp_enabled` | |
| `heat.ovr.pellet` | `app.heat.override.pellet` | `…switch.heizung.pellets` | `…switch.heizung.pellets_override` | `app.heat.selector.out` | `pellet` |
| `heat.ovr.flow_temp` | `app.heat.override.flow_temp` | `…number.heizung.flow_temp` | `…switch.heizung.flow_temp_override` | `app.heat.target.out` | `flow_temp` |
| `heat.ovr.pwm` | `app.heat.override.pwm` | `…number.heizung.pwm` | `…switch.heizung.pwm_override` | `app.heat.flow.out` | `pwm` |

`job.heat.ovr.wp.yaml` is the first of these as a job record; to set it
up:

```shell
moat link code transform.hass.override set -a -d ../moat-link-job/code.transform.hass.override.yaml
moat link job at heat.ovr.wp set -c transform.hass.override -t 0 \
    -p dst app.heat.override.wp \
    -p value home.ass.dyn.switch.heizung.wp \
    -p manual home.ass.dyn.switch.heizung.wp_override \
    -p actual app.heat.ha.wp_enabled
```

No two of these jobs watch the same path. Keep it that way until
moat-5m1s is fixed: two watches of the same path on one MoaT-Link client
don't both get updates.
