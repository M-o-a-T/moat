# moat-nnz: switchable Modbus-TCP bypass for server units

Status: all steps done.

Goal: transparent gatewaying for heat passthru (moat-n84.26). The Solvis
talks to our shim (`modbus.stiebelfake.yaml`, RTU server unit 101); in
passthru, every request must reach the real heat pump (polled by
`modbus.stiebel.yaml`, which also serves that client unit as TCP server
unit 3 on port 503) and the device's answer must come back unchanged.
Modbus-TCP is the transport, so no new RPC service is needed.

## Configuration

A server unit gets an optional section:

```yaml
bypass:
  when: !P path.to.bool.value
  dest:            # optional
    host: name
    port: 503      # optional, default 502
    unit: 3
```

- `when` is a path, or `[path, attr]`: watch `path`, the flag is
  `value.get_(attr)`. A missing or non-true value means "off". Heat
  passthru publishes `app.heat.passthru.state` as `{bypass: bool,
  switching: str|None}` (moat-n84.26), so its configs use
  `when: [!P app.heat.passthru.state, !P bypass]`.
- With `dest` (sender side, e.g. the shim): while the flag is true,
  every request to this unit is sent to `dest` via Modbus-TCP.
- Without `dest` (recipient side, e.g. the stiebel poller): only valid on
  a server unit that is attached to a client unit (`server:` key of a
  client unit). While the flag is true, every request is executed on the
  client unit directly: the cached registers are treated as stale, and
  the client unit's own writes (`src` registers) pause, so they don't
  fight the original controller. Polling (`dest`) continues.

`bypass` with `dest` is accepted both in `server[].units.N` and in the
config of a client unit that has `server:`; without `dest`, only in the
latter (a server-section unit has no client unit). It requires a
MoaT-Link client.

## Steps

1. **`Bypass` object** (`moat/modbus/dev/bypass.py`): parses the config,
   watches `when` (`link.d_watch`), exposes `active`, and has
   `forward(request) -> PDU`. Its target is a client `Unit`: for `dest`
   one obtained from the poller's `ModbusClient`
   (`host_service(host, port)` / `unit_scope(unit)`), else the attached
   client unit. Runs as a task in `dev_poll`'s task group.

2. **Dispatch.** `BaseModbusServer.process_request` checks
   `getattr(ctx, "bypass", None)`; if it is active, the request goes to
   `bypass.forward` instead of the context. This covers plain
   `UnitContext`s (shim) and `ServerUnitContext`s (attached client
   units) alike, including writes.

3. **Transparent replies.** Forwarding returns the device's response
   unchanged. `client.Unit.process_request` currently maps every error
   to `DEVICE_FAILURE`; change it so that a `ModbusError` returns the
   device's own exception response, and a timeout or connection loss
   returns `GATEWAY_TARGET_NO_RESPONSE`. Unit ID and transaction ID are
   restored by the server as now.

4. **Pause our own writes.** A client `Unit` gets a write gate:
   while it is closed, `Slot.write` returns without writing and the
   changed values stay marked as changed; opening it triggers a write of
   whatever changed meanwhile. The recipient-side `Bypass` closes the
   gate of its client unit while active.

5. **Wiring in `dev_poll`**: create the `Bypass` for server units and
   for attached client units; reject `bypass` without `dest` on a unit
   with no client unit, and any `bypass` without a link.

6. **Tests** (`tests/moat_modbus/test_bypass.py`, `Scaffold`, all TCP):
   a fake device server (C); poller B polls C and serves it as unit 3
   with `bypass: {when: …}`; poller A serves unit 101 from Link data
   with `bypass: {when: …, dest: B/3}`.
   - flag off: A answers from Link data, B from its cache (unchanged
     behaviour);
   - flag on: reads at A return C's live values, also for registers B
     doesn't poll; writes at A reach C;
   - C's exception (illegal address) arrives at A's client with the
     same code; C unreachable → `GATEWAY_TARGET_NO_RESPONSE`;
   - toggling the flag takes effect on the next request;
   - `when` as `[path, attr]`;
   - while B's bypass is on, B's `src` writes don't reach C; they are
     written when it goes off.

7. **Docs**: `docs/moat-modbus/dev-poll.md` (the `bypass` section;
   replaces the "forward: true not fully implemented" note if that's
   now moot), `moat/dev/heat/HEAT.md` §2.8 (replace the RPC-service
   description), and the example configs
   (`modbus.stiebelfake.yaml`, `modbus.stiebel.yaml`) with a commented
   `bypass` section pointing at `app.heat.passthru.state`.
