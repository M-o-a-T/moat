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
  constructor flag: `True`/"server" decodes incoming bytes as requests;
  `False`/"client" decodes as responses; `"monitor"` (RTU only) is a
  passive bus sniffer (see below).  Both share
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

## Monitor mode (RTU only)

`FramerRTU("monitor")` is a passive bus sniffer for tapping a live
master/slave RTU line without participating in it.  Sending is
prohibited: `buildFrame` raises `ModbusIOError`.  Received frames are
decoded as an alternating request/response sequence, starting with a
request -- each successfully decoded frame flips the expectation
(queryable via `FramerRTU.expecting_request`), so a request is followed
by its reply, then the next request, and so on.

Because the framer is sans-IO it cannot detect the inter-frame idle gap,
so the *caller* drives phase recovery: on an inter-frame timeout (no
more bytes within the window) the caller calls `resetFrame()`, which in
monitor mode clears the accumulator **and** returns the framer to
expecting a request.  This covers both a torn/garbled partial frame and
a silent slave (a request that drew no reply): in either case the next
frame on the bus is a fresh request.  `resetFrame()` must only be called
on a timeout, never after a successful decode.

Monitor mode is exclusive to RTU because the alternating-phase model
relies on the master/slave timing of a serial bus; `FramerTCP("monitor")`
is rejected at construction.
