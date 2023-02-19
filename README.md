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

There's a [Wikipedia article](https://en.wikipedia.org/wiki/Structured_concurrency).

A good Pythonic introduction is [here](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/).


## Repository Structure

This repository contains a lot of submodules, corresponding to separate `moat-XXX`
packages..

The submodule "main" contains the command-line front-end of the MoaT. Any
MoaT code that can reasonably be controlled by a command line hooks into
it, by way of a `_main` module with a `cli` object, which should be an
`asyncclick` command.

All other parts are submodules, so you can ignore the parts you don't want.

One mandatory submodule is "util". It contains a heap of semi-structured helper code
which the rest of the MoaT infrastructure depends on.

## Modules

### Libraries

These can be used standalone.

* dbus: an async DBus client.

* gpio: a library to read and write GPIO lines.

* modbus: an opinionated Modbus client and server library.

* mqtt: a MQTT broker, client library, and client command line front-ends.

* wire: a bidirectional link exchanging structured messages,
  with backends for serial and TCP.

* micro: Support for MoaT sattelites running MicroPython

### MoaT parts

* main, util: See above.

* kv: distributed masterless eventually-consistent key-value storage.

* pv: photovoltaics.

### MoaT-KV components

* kv-akumuli: Data storage to [Akumuli](https://docs.akumuli.org/), an
  efficient light-weight time series database

* kv-gpio: Connecting Moat-KV and MoaT-GPIO

* kv-hass: Use MoaT-KV as the MQTT back-end to Home Assistant

* kv-inv: Network inventory management (hosts, networks, VLANs, links between hosts)

* kv-knx: Link with KNX building automation networks

* kv-owfs: Connecting 1wire sensors

* kv-wago: A rudimentary interface for WAGO 330 controllers

### MoaT-PV components

* pv-bms: Battery management

More will follow.
