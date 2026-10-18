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
  `sensors` (power/compressor readings missing), `solvis`
  (the Solvis poll reports an error, see "Emergency end").

This item is the passthru unit's persistent state
(`state_path("passthru")` is exactly this path), so the unit uses its
`StateStore` for it, saving immediately on every change. A restart
resumes where it was; while the unit is down, the retained item keeps
everything as it is.

Request: `app.heat.passthru.request` (bool, retained; absent = false).

## Steps

0. **`moat.modbus` prerequisites** — done (5b2b2e3fb, 6dece0dce):
   - a. **Configurable request timeout per host**: a `timeout` key next
     to the units of a `hosts` / `hostports` entry (TCP; default 10 s as
     now), passed to `Host`. Serial ports already take `timeout` in
     their `serial` section; document it.
   - b. **`moat modbus dev poll` announces itself** with
     `link.announcing()` (service name from the systemd unit, as
     `announcing` discovers it; `MT_SERVICE` overrides), marked up once
     its servers run. `moat-link-host`'s service monitor then records
     `error.run.host.<path>` when the poller is gone or not up.

1. **`passthru` unit** — done. (`moat/dev/heat/passthru.py`, sans-IO core +
   `Unit` adapter, in `system/runner.UNITS` and `DEFAULT`).
   - Inputs: `request`, `pump` (`app.heat.pump.out`), `m_power`
     (`heat.s.pump.power`), `compr` (`heat.s.pump.compr.speed`,
     optional), `cfg.p_idle` (power below this counts as idle; default
     the pump unit's `start.min_power`).
   - Heat pump idle = power below `p_idle`, compressor (if configured)
     at 0; towards bypass additionally `pump.out.run == "off"`. These
     are published on change, so their age means nothing: only a
     missing value counts (`switching: sensors`).
   - `request != bypass`: if idle, flip `bypass` and clear `switching`;
     else set `switching` and wait. Request withdrawn while waiting:
     clear `switching`.
   - No `out` item: the state item says it all; the reason is logged.
   - Emergency end, see below.

2. **Consumers use the new shape** — done. (`(state or {}).get("bypass")`):
   - `pump`: see step 3. Also, it doesn't *start* while a switch towards
     bypass is pending (`bypass` false and `switching` set: `enabled` is
     false, reason `passthru`). A running heat pump finishes normally.
   - `watchdog`: status `passthru` while `bypass`.
   - Shared helper `passthru.passthru(value) -> bool` for the test.

3. **The pump unit during passthru** — done. It can't stand down: the Solvis
   runs the heat pump, but the circulation pump is ours (GPIO PWM via
   the flow unit), so it must follow the Solvis' own pump output
   `analog.out:4` (`heat.s.pump.rate.cmd`, 0…1; the pump is PWM
   controlled, so this is the duty cycle, as in the legacy bypass mode).
   - The Solvis poller (`modbus.heat.yaml`) polls that register every
     second (slot `1sec`, as in the example config already); keep it so.
   - While `bypass`, the pump unit
     - writes nothing to `cmd.mode`/`cmd.power` (the Solvis does, via
       the Modbus bypass);
     - writes the flow request `{mode: fixed, pwm: rate.cmd}` (clamped
       to 0…1), updated whenever the value changes; while the value is
       missing, `fixed` at `bypass_pwm` (new config, default 0.5), so
       the water keeps moving;
     - publishes `pump.out` with `run: off`, reason `passthru`, and the
       PWM it passes on;
     - keeps its state machine at `off` while bypassed;
     - skips its abort checks (critical errors, stale sensors, PWM
       daemon): the heat pump isn't ours.
   - The flow unit needs no change: it executes the request as usual,
     and the PWM override still wins. The frost unit needs nothing
     either: a PWM from someone else opens the loop valve.
   - No age check on `rate.cmd`: the poller publishes on change, so a
     steady value is old but valid. A failing Solvis poll ends the
     bypass instead (see "Emergency end").
   - When the bypass ends (normally or not), the pump unit enters
     `down`, as the legacy code did: heat pump off (`cmd.mode` off,
     `cmd.power` 0), the circulation pump keeps running until
     `t_out - t_in` is below `stop.delta`, then `off`. After a normal
     end the heat pump is idle already, so this is short. That first
     step re-sends all our outputs (`Step.force`), since the heat
     pump's commands are the original controller's at that point.

### Emergency end

If the Solvis can't be polled, `rate.cmd` freezes and our circulation
pump no longer follows the Solvis while it may still raise the heat
pump's power: risk of overheating. So the bypass is force-ended.

- `moat modbus dev poll` already reports poll failures to MoaT-Link's
  error subsystem (verified): an unreachable host at
  `error.app.modbus.tcp.<addr>.<port>`, an unresponsive one (after the
  host's request timeout, 10 s for TCP) at
  `….<port>.<unit>.<slot>`. Both are deleted on recovery.
- New passthru config `errors: list[Path]` (default empty: no check):
  error subtrees to watch, relative to `error`; production:
  - `app.modbus.tcp.<Solvis host>.502` (poll failures; the host name
    as one path element),
  - `run.host.<host>.<poller service>` (the poller process is gone, via
    step 0b).
  The unit watches each with a `TreeReader`.
- While `bypass` and any of them has an entry: set `bypass` false and
  `switching` `None` at once (no idle wait), reset
  `app.heat.passthru.request` to false (so it doesn't re-enter by
  itself; the HA switch shows "off"), log an error. The pump unit then
  runs `down` (step 3): heat pump off, water pump on until cooled.
- An entry also blocks entering bypass (`switching: solvis`).
- Detection delay: an unreachable Solvis at once; an unresponsive
  one after the host's request timeout (step 0a; set it to a few
  seconds for the Solvis); a dead poller after `moat-link-host`'s
  ping-down timeout. That monitor must run where the heat units'
  MoaT-Link server is (i3), or the record never appears; to be checked
  on the real setup.

4. **Other units** — nothing to do: `heat_valve`, `pellet`, `selector`, `target`,
   `errors`, `frost` keep running unchanged. While bypassed the pump
   unit reports `run: off` (reason `passthru`), so heat_valve uses its
   pre-heat test and the selector sees an idle heat pump; the burner is
   still requested when it's cold. `de_ice.fake`: while bypassed the
   Solvis reads the real register through the Modbus bypass, so nothing
   to do here.

5. **Configs and docs** — done: enable the `bypass` blocks in
   `examples/moat-dev-heat/modbus.stiebel{,fake}.yaml`; HEAT.md §2.8/§3.9
   (spec as implemented, open items resolved), `docs/moat-dev-heat`
   `schema.yaml` and `data.md` (state shape, writer, `passthru` no longer
   "planned"), and an HA switch for the request:
   `examples/moat-dev-heat/HA.md` gets a `switch.heizung.passthru` whose
   command is copied to `app.heat.passthru.request`; its state is the
   `bypass` element of `app.heat.passthru.state`, copied by
   `transform.copy.value` with its new `attr` parameter. No CLI
   command. I3.md: the
   `errors` setting, and that `moat-link-host` must run on i3.

6. **Tests** — done (`tests/moat_dev_heat/test_passthru.py`). The
   closed-loop test runs on `ClosedLoop`, which now also publishes a
   core's state when its step saves it (as the `StateStore` does):
   - core, table-driven: request while the heat pump runs is deferred
     (`switching: heatpump_idle`), switches once idle; switch back
     deferred while the Solvis runs it; request withdrawn while waiting;
     missing sensors → `switching: sensors`;
   - restart in either state resumes (state store);
   - an error entry (in any of the watched subtrees) while bypassed:
     immediate end, request reset; an entry blocks entering
     (`switching: solvis`); clearing it unblocks;
   - pump core: while bypassed no `cmd.*`, flow request `fixed` at
     `rate.cmd` (and at `bypass_pwm` while it's missing), `run: off`;
     doesn't start while a switch is pending; enters `down` when the
     bypass ends (heat pump off, water pump on until cooled);
   - watchdog: `passthru` status while bypassed;
   - E2E (Scaffold + simulator): units and plant run; request passthru
     while the heat pump runs → switch only after it has cooled down;
     the "original controller" (test code writing `cmd.mode`/`power`
     and `rate.cmd`) runs the heat pump; our units write nothing to
     `cmd.*`; the circulation PWM follows `rate.cmd`; switching back
     waits until it's idle. Second run: the Solvis "fails" (test writes
     an error entry) while it runs the heat pump: bypass ends at once,
     heat pump off, water pump runs until the loop has cooled. No Modbus devices:
     the forwarding is covered by moat-nnz's tests, and the whole chain
     gets tested on the real hardware.
