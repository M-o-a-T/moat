# The MoaT

"MoaT" is an acronym of "Master of all Things", which is either
aspirational or just plain pretentious. Take your pick.

If you assume that this repository contains the same stuff as a regular
moat, i.e. a lot of water of questionable quality (plus whatever the
castle's inhabitants wanted to get rid off), you might not be too far off
the mark.

Well, except for the water.


## Seriously …

The MoaT code comprises a lot of somewhat-opinionated code to control
various IoT devices. Among those are photovoltaics, irrigation, door
intercoms, and whatnot.

The core of MoaT is written in anyio-compatible asynchronous Python3,
written with Structured Concurrency principles in mind.

Satellite microcontrollers typically run MicroPython, again heavily using
structured async code: MicroPython supports taskgroups if you patch it
lightly.


### Structured what?

Structured Concurrency.

There's a [Wikipedia article](https://en.wikipedia.org/wiki/Structured_concurrency) about it.

A good Pythonic introduction is [here](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/).


## Repository Structure

The MoaT code is built using git submodules, corresponding to separate
`moat-XXX` packages.

The top module contains the command-line front-end of MoaT. Any
MoaT code that can reasonably be controlled by a command line hooks into
it, by way of a `_main` module with a `cli` object, which should be an
`asyncclick` group (or command).

The only mandatory submodule is "util". It contains a heap of
semi-structured helper code which the rest of the MoaT infrastructure
depends on. "moat-util" also has a command line; it serves as a convenient
example for building your own extension, and exports a
time-until-absolute-date calculator and a msgpack codec.


## Modules

### Components

* dbus: an async DBus client.

* gpio: a library to read and write GPIO lines.

* modbus: an opinionated Modbus client and server library.

* mqtt: a MQTT broker, client library, and client command line front-ends.

* wire: a bidirectional link exchanging structured messages,
  with backends for serial and TCP.

* micro: Support for MoaT sattelites running MicroPython

* kv: distributed masterless eventually-consistent key-value storage.

* ems: Battery management, photovoltaics, …

* src: MoaT source code management

* dev: support for specific devices


### Support Libraries

* pid: a PID controller with anti-wind-up, saveable state, bumpless transfer, and
  measurement noise suppression.


### MoaT-KV components

Moat-KV is a master-less distributed key-value storage system. It is
resistant to partitioning and intended to be always-on. It will not block
or lose updates in a partitioned network; inconsistent entries are
re-synchronized upon reconnection.

"moat.kv" is currently named "distkv". Conversion to MoaT is planned.

* akumuli: Data storage to [Akumuli](https://docs.akumuli.org/), an
  efficient light-weight time series database

* gpio: Connecting Moat-KV and MoaT-GPIO

* hass: Use MoaT-KV as the MQTT back-end to Home Assistant

* inv: Network inventory management (hosts, networks, VLANs, links between hosts)

* knx: Link with KNX building automation networks

* owfs: Connecting 1wire sensors

* wago: A rudimentary interface for WAGO 330 controllers


### MoaT-EMS components

EMS is an acronym for "Energy Management System".

* battery: Battery management

* inv: Inverter management

* sched: Energy storage scheduling

More will follow.

### MoaT-dev support

* heat: example for controlling a home's heating system (heat exchanger,
  pellet boiler, buffer for hot water and radiator-based heating).


# Support

Supporting MoaT is possible via [Paypal](https://paypal.me/MMoooaaTT) or
bank transfer (DE34430609671145580100, GENODEM1GLS).

Direct support via email or Zoom/Teamviewer is also available.
Contact [Matthias Urlichs](mailto:urlichs@m-u-it.de) for details.
