================================
MoaT bus message via serial link
================================

Low-level bus access is time critical; you need a realtime kernel and C
code to reliably access it from a Linux-based system like a Raspberry Pi.

To mitigate this problem, there is a simple serial encoding of MoaT bus
messages. The adapter from that to the MoaT bus can either run on a
Raspberry Pi (if you use the realtime kernel – or a very slow bus),
or it can run on a microcontroller that's connected to a "real" computer
via some serial interface.

"Serial" means that the controller uses actual, physical Tx and Rx lines.
Serial interface implemented on the microcontroller as firmware are
untested; these may or may not work under load, again depending on your bus
timing.

Serial packets are protected with a CRC-16. They must be transmitted
continuously, i.e. transmission may not pause during a packet.


Frame format
============

1 byte: \x01 to \x04 depending on priority. Lower is better.

1/2 bytes: length. If the first byte's bit 8 is set, it is the MSB of a
           2-byte length.

n bytes: header and data; see `doc/spec_message.rst` for details.

2 bytes: CRC-16, MSB first. Polynomial 0xAC9A, reversed.


ACKs
====

1 byte: \x06 acknowledges sending one message.

There is currently no provision for selectively reporting which messages
generated an ack or nack. TODO, ideally before freezing the format.


Debugging
=========

Any message beginning with a byte >= 0x20 is a console message. It must not
contain any bytes between \x00 and \x06 and should end with a line feed
(``\n``, 0x0A).

