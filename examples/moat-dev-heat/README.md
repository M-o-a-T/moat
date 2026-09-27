# Modbus poller configs for the heat controller

These are the production `/etc/moat/modbus.*.yaml` files, converted for
the MoaT-Link based `moat modbus dev poll` (moat-n84.27). Run one poller
per file:

```shell
moat modbus dev poll modbus.heat.yaml
```

| File | Contents |
| --- | --- |
| `modbus.heat.yaml` | Solvis controller, KWB pellet burner and buffer, SDM630/SDM720 meters |
| `modbus.aux.yaml` | SDM630/SDM720 meters on the other host, Solvis |
| `modbus.stiebel.yaml` | Stiebel heat pump |
| `modbus.stiebelfake.yaml` | Stiebel emulation for the Solvis controller |

## Changes from the MoaT-KV version

17 destinations written as `!P :mr.…` now are plain
paths. The `:mr` mark meant "raw MQTT, not retained" in the MoaT-KV
poller; path marks are deprecated and the Link poller does not use them.
These values are now retained. All affected paths are `grid.s.*` power
readings, marked with a comment.

The serial ports, which production reads from `!env DEV_STIEBEL` and
`!env DEV_SOLVIS`, are placeholders marked `EDIT` here, because the
repository's YAML check can't resolve unset environment variables. Put
the `!env` tags back when deploying.

Everything else, including the `heat.s.*` and `temp.*` paths, is
unchanged: since 2026-09-27 these are native MoaT-Link paths.

## Before deploying

- `heating/KWB/easyfire.yaml` is generated, not checked in. Run
  `code/rebuild.sh` in `moat/modbus/dev/_data/heating/KWB/` first.
- Once no poller writes to MoaT-KV any more, `gate.kv.heat` and
  `gate.kv.temp` can be deleted.
