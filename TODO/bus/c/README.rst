====================
MoaT BUS C interface
====================

Subdirectories
==============

app
+++

Building blocks for loading app-specific code onto a MoaT node.

design
++++++

Test and helper programs that informed the design of the MoaT bus.

There is no current code here.

boot
++++

The MoaT system's base code.

fakebus
+++++++

Helpers to hook up "embedded" programs to a fake bus implemented via a
Unix-domain socket.

include
+++++++

Collected C include files. All use ``moat/`` as prefix.

ldscripts
+++++++++

Specialized scripts for building the actual images.

moatbus
+++++++

Library modules to (de)construct a bus node.

tests
+++++

Test code.

Modules
=======

moat_serial_bus
+++++++++++++++

Exchange MoaT messages over a serial link.

Call `sb_byte_in` with incoming characters.


Definitions
-----------

* MOAT_SER_INBUF_SIZE

  buffer for incoming non-message data, enables `sb_getchar`.

