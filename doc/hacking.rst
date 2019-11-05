====================
Hacking the MoaT bus
====================

++++++++++++++
Code structure
++++++++++++++

References to code that do not have an extension apply to both Python
(``.py``) and a C implementations (``.c``/``.h``). Care must be taken to
keep those interoperable, though usage details necesarily differ.

----------------------
Physical bus interface
----------------------

``moatbus/handler`` implements sending and receiving buffered bus messages.
Both use an I/O-less strategy so that they can be used however necessary.

There currently is no implementation of a buffer-less sender or receiver.
Feel free to add one …

Encapsulation of bus messages is handled by ``moatbus/message``.

--------------------
Serial bus interface
--------------------

The serial adapter is in ``moatbus/serial.c``; there's also a Python
version. Both implement an I/O-less module which can be used in a variety
of environments.

++++++++++
Simulation
++++++++++

Debugging on embedded systems is difficult; you can't attach a debugger
because that disrupts bus timing.

Thus MoaT provides you with a variety of tools to simulate a MoaT bus in
software, hopefully enabling you to do the necessary debugging on the host.

------------------------
Low-level bus simulation
------------------------

The state of the bus wires is encoded to a byte; that byte is sent to a
daemon on a Unix socket which reads it, ORs it to the latest bytes from 
all other clients, and then sends the updated bus state to them, applying a
variable delay to simulate bus latency.

This bus is implemented by ``fakebus/bus.py``.

``fakebus/send`` and ``fakebus/recv`` send one message and receive any
number of messages, respectively. The common code for bus access is in
``fakebus/client``.

``fakebus/spam.c`` transmits random changes to the bus.

Finally, ``fakebus/serialbus.c`` treats its stdin/stdout like a serial wire
and bidirectionally forwards messages from that to the fakebus and back.

Like on the real bus, debugging disrupts the low-level bus simulator.

For a full-stack simulation, "fakebus/master.py" starts the serial adapter
and then attaches the bus master module to it.

-------------------------
High-level bus simulation
-------------------------

We'll use MQTT and send the message's bytes (without header) to the
test/raw/moatbus/SRC/DST/CODE topic.

