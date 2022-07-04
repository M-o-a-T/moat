============
The MoaT bus
============

--------------
Why a new bus?
--------------

Given that RJ45, PoE, VDSL, and multiple wireless options exist, you might
wonder why a new wired protocol might be useful.

The answer is that there is a rather large niche which doesn't have a good
solution. Assume, for the moment, that you want to deploy 100 sensors,
using cheap low-power microcontrollers and little or no bus attachment
hardware, on a possibly-unshielded random-topology cable, in an old house
with thick walls (or an office with concrete-and-steel walls) that eat your
WLAN for breakfast.

Also, radio is susceptible to random connectivity problems, dynamic mesh
radio is easy to get wrong and requires always-on nodes which again
requires too much power. Also², radio needs nontrivial hardware; for some
reason *g* most MCUs don't have a built-in mesh-capable radio.

A three-wire bus like 1wire is too fiddly to write bit-banging clients for.
(Several people have tried.) Also, 1wire doesn't have multi-master and you
don't want to poll the bus all the time.

CAN is difficult to get right without dedicated hardware. You need accurate
timing (<5%); also, the protocol overhead is rather high because the frame
size is limited to 8 bytes. That's OK for a car (high-speed bus with
differential signalling) but not if your bus extends over a building,
your MCU has no CAN hardware, your wiring isn't twisted-pair, and you want
to do firmware updates over the wire.

You could use half-duplex serial but there's the collision problem which
many UARTs are not equipped to handle. Also, your MCU might not have many
serial ports, and those might better required for firmware update,
debugging, or talking to peripherals.

Next problem: long wires have somewhat high impedance, which limit your
transmission speed. You could use I²C, but many hardware clients are too
susceptible to noise – in fact on many embedded CPUs the I²C interface can
freeze up. Also, you need 16 bus transitions per byte. This is rather slow.

The MoaT bus offers a solution to all of this. It requires four wires:
ground, power, and two data lines. It adapts easily to more than two wires.
It is multi-master and does not require particularly accurate timers:
timers for serial ports must be accurate within at most ~4% of the
bit rate, while MoaT work well with ~20% accuracy.

Downsides
---------

There are always compromises. With MoaT, the main problem is that it's a
bit-banging interface (well, until somebody writes an FPGA implementation,
which is unlikely as of 2021) which requires reasonably-fast interrupts.
While the current proof of concept implementattion runs in the Arduino main
loop, that's far too slow and doesn't allow the MCU to sleep.

While MoaT is designed for small(ish) MCUs, packet assembly and disassembly
is somewhat expensive in terms of both CPU speed and memory: the boot
loader for Cortex-M CPUs barely fits in 32k, thus online firmware upgrades
or non-trivial applications requires 64k of flash storage. The situation
on ATmega CPUs is likely to be worse.

----------------------
Principle of operation
----------------------

A bus with N wires can assume 2^n states. Our self-timing requirement
enforces *some* transiton between states. Thus each time slot can transmit
log2(2^n-1) bits of information.

We still need to transmit binary data. The optimal message size on a
two-wire system ends up as 7 transitions which carry 11 bits of information
(log2(3^7)). Using three wires, we can send 14 bits using 5 transitions;
four wires, 11 bits using 3 transitions.

Since a message can contain excess bits (3^7 > 2^11), we can use an
"illegal" sequence to terminate the message. Bus messages thus don't need a
length byte and can be generated on the fly if necessary.

A small header carries addressing and a few bits of message type
information. All messages are terminated with a CRC. Every message must be
acknowledged.

The details are documented in ``doc/spec_wire.rst``.


----------
Addressing
----------

More than 100 devices on a single bus are not realistic, esp. when the bus
supplies power to all of them. Device addresses on the MoatBus thus are 7
bits wide. More devices are possible with gateways.

Lots of communication flows between small dumb devices ("clients") and some
central system ("server"). On the MoatBus there may be more than one server,
so the server addresses get 2 bits. Server address 0 is reserved for
broadcast messages. Three "real" servers is deemed to be sufficient for
redundancy.

Short addresses are nice, but so is the ability to plug a new device into
the bus and have that device Just Work. Thus every device needs a MAC,
CPU serial number, or some other unique address; fortunately most embedded
CPU support either a hardware serial number or an EEPROM area we can use.
The client initially uses its hardware address to request a bus address
from the master.


Message content
---------------

MoatBus devices shall be auto-discoverable. Each device carries a data
dictionary; if there's not enough ROM for it, the dictionary may be stored
on the server and referred to by name.

Access to all features of a device is mediated by the dictionary. It may
declare discoverable or even configurable shortcuts that can be used to
shorten bus messages and simplify firmware code.

The details are documented in ``doc/spec_message.rst``.


--------------
Infrastructure
--------------

One bus client runs gateway firmware which implements a transparent
bidirectional link from the MoaT bus to its serial port. An embedded
computer (Raspberry Pi, ESP32, …) then relays to MQTT.

This allows the daemons which do address assignment, message relaying, and
data collection to operate independently. In particular, each part can be
debugged or restarted without affecting the other components of the MoaT
bus system.


The details are documented in ``doc/spec_infra.rst``.


------------
MoatBus code
------------

The MoaT bus is implemented in three programming languages: C, Forth, and Python.

C
====

The MoatBus C code runs on top of the `RIOT`_ embedded operating system
because it's too complex to not use multiple threads.

The code is split into "boot" and "app" parts; the intent is for the
application to be update-able over the wire. Same for the boot code, if it
can be squeezed into the app area.

The Moat Bus does not use server-side C code.

.. _RIOT: https://www.riot-os.org/

Building the client
-------------------

Run ``make`` in the ``c/boot`` subdirectory.

Python
======

Python is used extensively for the host system: read and dispatch serial
bus messages, allocate addresses, interface with a message bus (MQTT),
and whatnot.

A MicroPython port for the client side is possible but has not been started
yet.

Forth
=====

Forth is an interesting alternative for clients that are too small to run
MicroPython but complex enough that running an interactive interpreter on
them makes sense.

Some work to support a Mecrisp Stellaris-based client has been done.

