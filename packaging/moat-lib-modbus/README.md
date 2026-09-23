# moat-lib-modbus

% start synopsis
% start main

A sans-IO Modbus protocol core implementing the minimal subset used by
``moat.modbus``: PDU encoding/decoding for function codes 1, 2, 3, 4,
5, 6, 15, 16, plus TCP (MBAP) and RTU framers with a client/server
role flag, and an RTU-only ``monitor`` role for passive bus sniffing.

Stdlib only -- no ``pymodbus``, no ``anyio``.

% end synopsis

## Design

The library is strictly sans-IO: it never opens a socket, touches a
serial port, sleeps, waits, or spawns a task.  Every component is a
pure transform -- bytes in -> messages/PDUs out, messages in -> bytes
out.  The only mutable state permitted is a framer's internal byte
accumulator.  All real I/O stays in ``moat.modbus``.

### Role flag

The same function-code byte decodes to a request on a server and a
response on a client.  The role is therefore a constructor flag on the
framer itself: ``FramerTCP(role)`` / ``FramerRTU(role)`` where ``role``
is ``True`` / ``"server"`` (decode incoming bytes as requests),
``False`` / ``"client"`` (decode as responses), or -- for RTU only --
``"monitor"`` (passive bus sniffer; see below).

### Monitor mode (RTU only)

``FramerRTU("monitor")`` taps a live master/slave RTU line without
participating in it.  Sending is prohibited (``buildFrame`` raises
``ModbusIOError``).  Frames are decoded as an alternating
request/response sequence starting with a request; each decoded frame
flips the expectation (queryable via ``expecting_request``).  Since the
framer is sans-IO it cannot time the inter-frame gap, so the caller
calls ``resetFrame()`` on an inter-frame timeout, which clears the
accumulator and returns the framer to expecting a request -- covering
both torn partial frames and silent slaves.  Monitor mode is RTU-only;
``FramerTCP("monitor")`` is rejected.

% end main
