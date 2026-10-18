# moat-nnz: raw-request RPC service for `moat modbus dev poll`

Goal: a client unit of `moat modbus dev poll` can announce a MoaT-Link
service that executes raw Modbus requests on that unit, sharing the bus
with the poller's own requests. Needed for heat passthru (moat-n84.26:
the Solvis shim forwards the original controller's requests verbatim).

## Findings

- Every request of a client unit goes through `HostCommon.execute`
  (`moat/modbus/client.py`), under the host's `CapacityLimiter`. A serial
  host has capacity 1, so one request is on the wire at a time; TCP
  requests are matched by transaction ID. Raw requests that use the same
  `execute` are therefore serialised with polling for free.
- `moat.lib.modbus.pdu` has FC 1–6, 15, 16. **FC 23** (read/write
  multiple registers) is missing.
- `execute` raises `ModbusError(result)` for exception responses. It
  wraps a PDU, which the RPC codec can't carry; exceptions only cross
  MoaT-Link intact when registered with `moat.lib.proxy.as_proxy`.
- Services: `link.announcing(path, service=MsgHandler, host=...)`;
  callers use `link.get_service(path)` (see
  `tests/moat_link/test_service_refresh.py`). The announcement goes away
  when the context ends.

## Steps

1. **FC 23 in `moat.lib.modbus`.** `ReadWriteMultipleRegistersRequest`
   / `…Response`: encode/decode in both roles, registered with the
   decoders. Tests in `tests/moat_lib_modbus` (round trip, wrong
   lengths). Server-side handling of FC 23 in `moat.modbus.server` is
   not part of this issue (the passthru shim's forwarding is).

2. **Raw requests on a client `Unit`.** `Unit.request(fc, addr, *,
   count=None, values=None, w_addr=None) -> list[int] | list[bool] |
   None`: builds the PDU for FC 1–6, 15, 16, 23, runs it through
   `host.execute`, returns the read registers/bits (None for pure
   writes). FC 23 reads `count` at `addr` and writes `values` at
   `w_addr`. No range checks beyond what the PDU encoder needs.

3. **Serialisable Modbus exceptions.** `ModbusError` keeps its
   behaviour but is constructible from `(function_code,
   exception_code)` and registered with `as_proxy("_mbErr")`, so an RPC
   caller gets a `ModbusError` whose `.code` is the device's exception
   code. Transport errors (timeouts, connection loss) propagate as they
   are.

4. **The service.** `moat/modbus/dev/service.py`: `RawService(MsgHandler)`
   with `cmd_req(fc, addr, count=None, values=None, w_addr=None)` →
   `Unit.request`. `ClientDevice._ctx` announces it when the unit's
   config has

   ```yaml
   service:
     path: !P modbus.stiebel   # run.host.<host>.<path>
     host: heat                # optional; default: this machine's name
   ```

   and a MoaT-Link client is available. The announcement lives as long
   as the device, so it vanishes when the unit (or the poller) stops.
   Document the key in `docs/moat-modbus` (device config) and add
   `service` to the config schema, if there is one.

5. **Tests** (`tests/moat_modbus/test_service.py`, fake Modbus server
   from `test_dev_server.py` plus `Scaffold`):
   - RPC read/write for each FC (incl. 23 once the fake server handles
     it, else against a stub unit) equals direct `Unit` access;
   - polling and a burst of RPC requests on a host with capacity 1: the
     fake server never sees two requests in flight;
   - an illegal address raises `ModbusError` with
     `ILLEGAL_DATA_ADDRESS` at the RPC caller;
   - the service announcement disappears when the device context ends.

## Open questions (for review)

- One generic `req` command (above) vs. one command per function code.
  Generic keeps the shim's forwarding a 1:1 mapping.
- Announcement host default: this machine (as above), or required?
- Add a CLI (`moat modbus dev req PATH FC ADDR …`) for manual testing,
  or is `moat link` generic RPC enough?
