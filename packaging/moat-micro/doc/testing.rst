==================
Testing MoaT.micro
==================

++++++++++++++++
Unix MicroPython
++++++++++++++++

Setting the LOG_BRK envvar to 1 forces a breakpoint when logging an error.

-------------
Running tests
-------------

The standard test suite includes MicroPython tests. No further action is
required, other than building the Unix port of MicroPython in the first
place.

-------------------
Test infrastructure
-------------------

Test commands
*************

_test.MpyCmd
============

The ``_test.MpyCmd`` app starts a locally-built MicroPython
subprocess and runs a MoaT link to its stdin/stdout.

Its MoaT system uses the app's ``cfg`` config value as its configuration.

_test.MpyRaw
============

Likewise but stdio is exported as a bytestream.

Loop
====

A loopback link.

Messages are MsgPack-encoded (and immediately decoded again of course).
Note however that both sides use the same Proxy cache, thus this link
exercises encoding of proxied classes, but random objects are still passed
transparently.

echo
++++

Returns a map with the member ``r`` that replicates its ``m`` argument.

+++++++++++++++
Real satellites
+++++++++++++++

Regular tests with real satellites are difficult because their flash
storage only supports a limited number of write cycles.

Nevertheless, we do support testing on modules where either enough RAM is
available (ESP32 with external SPI SRAM), or for additional testing for
releases (RP2040). Both require additional connections to their boot and
reset inputs.

MoaT hardware designs support this with an USB plug with external power
control inputs, as well as a small hub that includes a GPIO chip if the
test host doesn't supply 3.3V pins.

