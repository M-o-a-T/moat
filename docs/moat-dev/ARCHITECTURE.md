# Architecture — moat.dev

CLI-driven device controllers for physical hardware (heaters, motors).
Registered as the `moat.dev` command group (`_main.py`).

## Subpackages

### `heat/` — heating system controllers

- **`kwb.py`** — KWB EasyFire pellet burner via Modbus; sends periodic
  "lifetick" updates. Uses `moat.util.yload`, `moat.modbus.dev.poll.dev_poll`,
  and optionally `moat.link.client.Link`.
- **`solvis.py`** (2269 lines) — manual control of SolvisMax+SolvisLea
  heating combination. Heavy user of `moat.util` (`attrdict`, `combine_dict`,
  `pos2val`/`val2pos`, `yload`/`yprint`, `t_iter`), plus `moat.kv.client`,
  `moat.lib.path`, `moat.lib.pid`.

### `sew/` — SEW MOVITRAC motor controllers

- **`_main.py`** — CLI with `run` and `set` commands. Merges config from
  multiple sources using `moat.util.combine_dict`/`merge`/`load_cfg`.
- **`control.py`** — `_Run` class managing Modbus registers (holding registers
  for control/status) and MQTT publishing. Uses
  `moat.modbus.client.ModbusClient`, `moat.mqtt.client.open_mqttclient`,
  `moat.util.attrdict`/`srepr`. Registers as a config provider via
  `moat.lib.config.register`.

## Integration

Deeply integrated with `moat.util` (config, YAML, path math), `moat.modbus`
(industrial comms), `moat.mqtt`/`moat.kv`/`moat.link` (messaging), and
`moat.lib.config` (registration). Communicates over the `moat.bus` hardware
bus where applicable.

## Entry points

`moat dev heat {kwb,solvis,…}` and `moat dev sew {run,set}` via
`dev/heat/_main.py` and `dev/sew/_main.py`.
