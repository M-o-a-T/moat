The MoaT Bus
============

This code implements the main parts of a "real" MoaT bus.

Modules
+++++++

bus
---

The actual bus client code.

mcrc
----

MoaT's 16-bit and 32-bit CRC tables, plus lookup code.

The tables come in 4- and 8-bit wide variants, depending on whether
``HAVE_MEM_1`` (16bit) and ``HAVE_MEM_2`` (32bit) are defined, as this
saves a heap of memory at the expense of two lookups instead of one.

msg
---

Basic helpers for bus messages.

serial
------

A serial (instead of wire-based) bus interface.

TODO: This code does not even try to be half-duplex-friendly.

util
----

Mostly mini-float support, to save on bus bandwidth.
