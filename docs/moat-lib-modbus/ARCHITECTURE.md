# Architecture -- moat.lib.modbus

A sans-IO Modbus protocol core, stdlib-only (no ``pymodbus``, no
``anyio``).  Pure data-in/data-out; no sockets, no clocks.  Fully
unit-testable without hardware.

## Modules

- **`errors.py`** -- `ExcCodes` (IntEnum with standard Modbus exception
  codes and source-compatibility aliases) and `ModbusIOError(Exception)`.
- **`_crc.py`** -- `crc16(data) -> int`: CRC-16/Modbus, polynomial
  `0xA001`, init `0xFFFF`, LSB-first, byte-wise loop.
- **`pdu.py`** -- PDU base + request/response classes for FC 1, 2, 3, 4,
  5, 6, 15, 16, plus `ExceptionResponse`.  Each class has
  `function_code`, `encode()`, `decode()`, `isError()`.
  `transaction_id`/`unit_id` are mutable attributes stamped by the
  framer.  A role-aware `decode_pdu(data, *, server)` maps the leading
  FC byte to the request class (server) or response class (client).
  Each `Request` carries `execute(context)` operating against a
  `Context` Protocol with `get_values`/`set_values`.
- **`framer.py`** -- `FramerTCP(role)` (MBAP: 7-byte header + PDU) and
  `FramerRTU(role)` (address + PDU + 2-byte CRC).  `role` is a required
  boolean constructor flag: `True`/"server" decodes incoming bytes as
  requests; `False`/"client" decodes as responses.  Both share
  `buildFrame(msg) -> bytes` and `handleFrame(data, ...) -> (used, pdu|None)`
  with `used==0` meaning "incomplete, feed more bytes".

## Sans-IO principle

The library never opens a socket, touches a serial port, sleeps, waits,
or spawns.  The only mutable state is a framer's internal byte
accumulator.  All real I/O stays in `moat.modbus`.

## Role flag

The same FC byte decodes to a request on a server and a response on a
client.  The role is a constructor flag on the framer, delegated to
`decode_pdu(..., server=self.role_is_server)`.  No separate `DecodePDU`
object is threaded by callers.
