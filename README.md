# The MoaT

% start main

"MoaT" is an acronym of "Master of all Things", which is either
aspirational or just plain pretentious. Take your pick.

If you assume that this repository contains the same stuff as a regular
moat, i.e. a lot of water of questionable quality (plus whatever the
castle's inhabitants wanted to get rid off), you might not be too far off
the mark.

Well, except for the water.


## Seriously …

The core of MoaT is written in asynchronous Python3,
based on Structured Concurrency principles.

Satellite microcontrollers run MicroPython, again using structured async
code. MicroPython supports taskgroups if you patch it lightly.

% end main


### Structured what?

Structured Concurrency.

There's a [Wikipedia article](https://en.wikipedia.org/wiki/Structured_concurrency) about it.

A good Pythonic introduction is [here](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/).


## Contents

- MoaT-Link: Storage of semi-volatile data
  - Structured messaging via MQTT
  - Data conversion (CBOR, JSON, plaintxt, msgpack, modbus)
  - Bidirectional gateway
  - Host and service monitoring
  - Error notification and alerting
- MicroPython integration
  - taskgroups
  - incremental updates
  - seamless RPC
- Many support libraries:
  - Async RPC, with bidirectional data streaming
  - MQTT
  - Modbus
  - GPIO
  - PID control
  - Async console I/O (with multi-line input, history, tab completion, and all that)
  - Async read/write streams
- Process control (physical processes, not computers) (TODO)
  - heat pumps
  - motor controllers
- Solar energy (TODO)
  - battery monitor
  - inverter control
  - energy scheduling
- MoaT-KV (key-value storage, deprecated)
  - with various adapters that need a rewrite (TODO)

## Repository Structure

The MoaT code lives in a single mono-repository.

### History

The MoaT modules once were stored in separate repositories. This however
caused too many coordination problems. Thus they were all imported into the
main repo, including their history, which is why this repository has
way too many initial commits. ;-)

## Issues, pull requests, et al.

As of 2026-01, we're on [Github](https://github.com/M-o-a-T/moat).

This will change, in favor of Codeberg and Radicle. TODO.


## Support

Supporting MoaT is possible, ideally via bank transfer
(DE07430609671145580101, GENODEM1GLS). If you can't do that,
[Paypal](https://paypal.me/MMoooaaTT) is possible.

Direct support via email or Zoom/Teamviewer is also available.
Contact [Matthias Urlichs](mailto:urlichs@m-u-it.de) for details.
