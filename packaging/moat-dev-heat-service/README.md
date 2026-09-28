# systemd units for the MoaT heating controller

% start main
% start synopsis

systemd units that run the MoaT heating controller (`moat dev heat`):
its units, the software PWM daemon and the Solvis Modbus monitor.

% end synopsis

| Unit | Runs |
| --- | --- |
| `moat-heat@UNIT.service` | one heat unit: `moat dev heat run UNIT` (`target`, `heat_valve`, `flow`, `pump`, `pellet`, `selector`, `errors`, `frost`, `watchdog`) |
| `moat-heat.service` | all units but the watchdog, in one process (single-host setups) |
| `moat-heat-pwm.service` | the software PWM daemon (`moat dev heat pwm`), needs GPIO access |
| `moat-heat-modbus-mon.service` | the Solvis Modbus poll monitor (`moat dev heat modbus_mon`) |

Either enable `moat-heat.service` or the per-unit instances, not both.
Run `moat-heat@watchdog.service` on a different host than the pump unit.

The Modbus pollers (`moat-modbus-poll@.service`, package `moat-modbus`)
and the MoaT-Link gateways (`moat-link-gate@.service`, package
`moat-link-server`) have their own units.

All units read `/etc/moat/moat.yaml`, plus `/etc/moat/heat.env` for
environment settings, and run as user `MoaT-Heat` (group `MoaT`), except
the PWM daemon, which runs as root for GPIO access.

% end main
