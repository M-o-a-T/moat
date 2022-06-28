# Micropython code

This directory contains MoaT support for Micropython.

## Principle of Operation

MoaT for Micropython uses a single serial connection to the controller.
You can use a basic TTL-serial line, or serial-over-USB, or even a TCP
connection if the target is an ESP32.

Messages are encoded with "msgpack". They comprise, in effect, a reliable,
asynchronous bidirectional RPC ("Remote procedure Call") system. Thus,
code on the Micropython system can seamlessly request resources from
the host.

If the serial line is unreliable (hint: it probably is), MoaT supports a
framing protocol that prevents invalid messages, and a realiability layer
(roughly modelled on X.75) with selective ACKs that re-transmits any lost
messages and ensures message order is maintained.

## Initial setup

The "mpy-setup" script uses the standard Micropython REPL to upload
the code. No manual intervention required.

## Requirements

You currently need a patched version of MicroPython because MoaT
extensively uses taskgroups, which are subtly incompatible with standard
µPy (the C-implemented `Task` class isn't hashable).

Simply go to `moat-bus/python/lib/micropython/ports/rp2`, run "make" to
build your own, boot to upload mode, and copy to the Pi.
