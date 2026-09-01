# moat-lib-modbus

% start synopsis
% start main

A sans-IO Modbus protocol core implementing the minimal subset used by
``moat.modbus``: PDU encoding/decoding for function codes 1, 2, 3, 4,
5, 6, 15, 16, plus TCP (MBAP) and RTU framers with a client/server
role flag.

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
is ``True`` / ``"server"`` (decode incoming bytes as requests) or
``False`` / ``"client"`` (decode as responses).

% end main
