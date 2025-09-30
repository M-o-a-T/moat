# MoaT EMS Battery

This module implements a generic battery controller.

The client is a microcontroller, e.g. an ESP32 or a RP2040. It runs
MicroPython and talks to the server via the MoaT messaging protocol.

The server side runs in the MoaT multiplexer that talks to the battery.
It typically uses a web page for setup, and/or connects to DBus.


## Rationale

One of the MoaT project's objectives is to implement a uniform,
multiplexable front-end for various devices.

Battery management systems typically have interfaces with device-specific
command sets that can only be talked to by a single client, so devising a
common language makes sense.

Also, a BMS may not have the required features. For instance, you might
want to chain multiple batteries in series or in parallel. Or, the BMS
firmware does not understand that some battery chemistries require adaptive
strategies for charging that cannot be expressed with a single charge
curve.


### Why so complex?

The client connects to the actual BMS hardware with TTL serial, SPI, I²C,
RS485, CAN, or similar. For the most part, these interfaces do not support
galvanic separation, may not even exist on a server.

The client needs to constantly monitor battery current, cell and system
voltage, battery temperature et al.. It must be able to disconnect the
battery's relay if any parameter exceeds the cell and battery
specifications. This function should run continuously even if communication
with the server fails.


## Setup

As typical clients are resource-constrained, you need to add the Battery
management code to the MicroPython flash image. Add this repository's
manifest, from `moat/micro/_embed/manifest_bms.py`, alongside the one from
`moat.micro`.

Add a "BMS" app to the "moat.micro" configuration::

    apps:
      …
      bat1: bms.std.Cmd

    bat1:
      …

The "bat1" section (or however you want to name it) is described in
`moat/ems/battery/_cfg.yaml`. More extensive documentation is TODO.

Start the client and multiplexer normally; the MoaT BMS will run as part of
the multiplexer.


### Server-only operation

Some systems don't need a client. A commercial BMS with an RS485 interface
e.g. can be connected directly to the server, no intermediate client required.

In this case, set the "dev:" entry in the "port:" section to "null".


## Modules

Right now the only battery model is "std". It connects several subsystems:

* system voltage, current and temperature

* cell voltage and temperature

It controls

* the balancing system(s)

* the battery relay

Also, it sends the battery's SoC and its voltage and current limits to
whichever program requires them, as well as displaying them to the user.
