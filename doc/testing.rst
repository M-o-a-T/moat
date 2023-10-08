==================
Testing MoaT.micro
==================

++++++++++++++++
Unix MicroPython
++++++++++++++++

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
subprocess. The ``cfg`` member of its configuration contains its local
setup.

_test.Cmd
=========

This app contains a couple of commands useful for testing.

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

MoaT hardware designs supportthis with an USB plug with external power
control inputs, as well as a small hub that includes a GPIO chip if the
test host doesn't supply 3.3V pins.

