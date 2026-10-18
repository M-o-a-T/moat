# moat-n84.26: passthru mode

Hand the heat pump to its original controller (the Solvis) for
maintenance, and take it back, only while the heat pump is idle. The
Modbus side is done (moat-nnz: switchable `bypass` of server units).

## State item

`app.heat.passthru.state` = `{bypass: bool, switching: str | None}`:

- `bypass`: the original controller is in charge. This is what the
  Modbus bypasses watch (`when: [!P app.heat.passthru.state, !P bypass]`)
  and what the heat units act on.
- `switching`: what a requested switch is waiting for, `None` when the
  request is satisfied. Values: `heatpump_idle` (normally),
  `sensors` (power/compressor readings missing or stale).

This item is the passthru unit's persistent state
(`state_path("passthru")` is exactly this path), so the unit uses its
`StateStore` for it, saving immediately on every change. A restart
resumes where it was; while the unit is down, the retained item keeps
everything as it is.

Request: `app.heat.passthru.request` (bool, retained; absent = false).

## Steps

1. **`passthru` unit** (`moat/dev/heat/passthru.py`, sans-IO core +
   `Unit` adapter, in `system/runner.UNITS` and `DEFAULT`).
   - Inputs: `request`, `pump` (`app.heat.pump.out`), `m_power`
     (`heat.s.pump.power`), `compr` (`heat.s.pump.compr.speed`,
     optional), `cfg.p_idle` (power below this counts as idle; default
     the pump unit's `start.min_power`), `cfg.max_age` for staleness.
   - Heat pump idle = power below `p_idle`, compressor (if configured)
     at 0, both fresh; towards bypass additionally `pump.out.run ==
     "off"`.
   - `request != bypass`: if idle, flip `bypass` and clear `switching`;
     else set `switching` and wait. Request withdrawn while waiting:
     clear `switching`.
   - No `out` item: the state item says it all; the reason is logged.

2. **Consumers use the new shape** (`(state or {}).get("bypass")`):
   - `pump`: stands down while `bypass` (as now for `"original"`), and
     doesn't *start* while a switch towards bypass is pending (`bypass`
     false and `switching` set: `enabled` is false, reason `passthru`).
     A running heat pump finishes normally.
   - `watchdog`: status `passthru` while `bypass`.
   - Shared helper `link.passthru(value) -> bool` for the test.

3. **Circulation pump during passthru** (the open item): as in the
   legacy bypass mode, the flow unit follows the Solvis' own pump output
   `heat.s.pump.rate.cmd` (0…1: the pump is PWM controlled, so it is
   used as PWM directly, as in the legacy code). New flow inputs `passthru` and `rate_cmd`; while `bypass`:
   mode `passthru`, PWM = clamped `rate_cmd`; a stale/missing value
   holds the last PWM for `freeze`, then `safe_pwm` (as for stale
   sensors). The PWM override still wins. Without this the pump unit's
   last request (`off`) would keep the water pump off while the Solvis
   runs the heat pump. The frost unit needs nothing: a PWM from someone
   else opens the loop valve.

4. **Other units**: `heat_valve`, `pellet`, `selector`, `target`,
   `errors`, `frost` keep running unchanged. While bypassed the pump
   unit reports `run: off` (reason `passthru`), so heat_valve uses its
   pre-heat test and the selector sees an idle heat pump; the burner is
   still requested when it's cold. `de_ice.fake`: while bypassed the
   Solvis reads the real register through the Modbus bypass, so nothing
   to do here.

5. **Configs and docs**: enable the `bypass` blocks in
   `examples/moat-dev-heat/modbus.stiebel{,fake}.yaml`; HEAT.md §2.8/§3.9
   (spec as implemented, open items resolved), `docs/moat-dev-heat`
   `schema.yaml` and `data.md` (state shape, writer, `passthru` no longer
   "planned"), and an HA switch for the request:
   `examples/moat-dev-heat/HA.md` gets a `switch.heizung.passthru` whose
   command is copied to `app.heat.passthru.request` and whose state is
   `app.heat.passthru.state`'s `bypass`. No CLI command.

6. **Tests** (`tests/moat_dev_heat/test_passthru.py`):
   - core, table-driven: request while the heat pump runs is deferred
     (`switching: heatpump_idle`), switches once idle; switch back
     deferred while the Solvis runs it; request withdrawn while waiting;
     stale sensors → `switching: sensors`;
   - restart in either state resumes (state store);
   - pump core: no `cmd.*`, no flow request while bypassed; doesn't
     start while a switch is pending;
   - watchdog: `passthru` status while bypassed;
   - flow: follows `rate_cmd` while bypassed, override wins, stale
     handling;
   - E2E (Scaffold + simulator): units and plant run; request passthru
     while the heat pump runs → switch only after it has cooled down;
     the "original controller" (test code writing `cmd.mode`/`power`
     and `rate.cmd`) runs the heat pump; our units write nothing to
     `cmd.*`; switching back waits until it's idle. No Modbus devices:
     the forwarding is covered by moat-nnz's tests, and the whole chain
     gets tested on the real hardware.
