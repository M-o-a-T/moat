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
requires too much power. Also², radio needs nontrivial hardware and power.
Most MCUs don't have built-in mesh-capable radio.

A three-wire bus like 1wire is too fiddly to write bit-banging clients for.
(Several people have tried.) Also, 1wire doesn't have multi-master and you
don't want to poll the bus all the time.

CAN is difficult to get right without dedicated hardware. You need accurate
timing (<5%); also, the protocol overhead is rather high because the frame
size is limited to 8 bytes. That's OK for a car (high-speed bus with
differential signalling) but not if your bus extends over a building,
your MCU has no CAN hardware, your wiring isn't twisted-pair, and you want
to do firmware updates over the wire.

Half-duplex serial doesn't work either because most UARTs are not equipped
to handle half-duplex operation with collision detection. Also, your MCU
might not have many serial ports, and those might better required for
firmware update, debugging, or talking to peripherals.

Next problem: long wires have somewhat high impedance, which limit your
transmission speed. You could use I²C, but many hardware clients are too
susceptible to noise – in fact on many embedded CPUs the I²C interface can
freeze up. Also, you need 16 bus transitions per byte. This is rather slow.


The MoaT approach
-----------------

The MoaT bus offers a unique solution. It requires four wires:
ground, power, and at least two data lines. It adapts easily to more than
two wires, with much better efficiency. It is multi-master and has quite
modest hardware requirements:

* pin-level interrupts (latency: somewhat less than the baud rate)
* a timer/counter (free-running, no interrupts)
* periodic calls from the main loop while active

----------------------
Principle of operation
----------------------

A bus with N wires can assume 2^n states. Our self-timing requirement
enforces *some* transiton between states. Thus each bus transition can
send log₂(2^n-1) bits of information.

On a two-wire system this is 1.58 bits. We combine multiple such
transactions until the overhead is minimized: 7 bus transitions can send
11.09 bits.

The 0.09 bits translate to 139 states, allowing us to send 7 bits that
might be required to fill a message's last byte, or to signal that the
trailing byte is garbage.

Messages end with an 11-bit CRC. The CRC is calculated over the actual
on-the-wire bits.

Messages are started with a single transition that (roughly) indicates
message priority. They end with an "illegal"

More wires?
-----------

For three wires, the optimal size is 5 transitions (14.036 bits).
However, surprisingly the advantage over using four transactions with 11.22
bits is only 2% (185 bus transitions instead of 188 for a 64-byte message,
not counting framing/CRC) and disappears or even reverses for shorter messages.

Four wires yield 11.72 bits (3 transitions) or 15.62 bits (4 transitions).
In practice there is no advantage of using more than 11 bits.

A 64-byte message (512 bits) thus requires 329 bus transitions for two
wires, 188 for three, and 141 transitions on four wires. The achievable
total transmission rate depends on bus topology and needs to be discovered empirically.

On a four-wire bus, perfect efficiency would be achieved using ten
transactions (39.068 bits); however, this is much too large: encoding would
require 64-bit division. Supporting small CPUs requires limiting 

struggle with 16-bit division. would require a >16-bit division or a
large lookup table. As both are too much overhead for cheap 8-bit
controllers, we limit the size to 7 bits. As before, this yields four
"out-of-band" values for signalling.

A small header carries addressing and a few bits of message type
information. All messages are terminated with an 11-bit CRC.

The details are documented in ``doc/spec_wire.rst``.


----------
Addressing
----------

More than 100 devices on a single bus are not realistic, esp. when the bus
supplies power to all of them. Device addresses on the MoatBus thus are 7
bits wide. More devices are possible with gateways.

Lots of communication flows between small dumb devices ("clients") and some
central system ("server"). On the MoaT bus there may be more than one server,
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

MoaT bus devices shall be auto-discoverable. Each device carries a data
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
debugged or restarted without affecting the other components of the system.

The details are documented in ``doc/spec_infra.rst``.


------------
MoatBus code
------------

The MoaT bus will be implemented in three programming languages: C, Forth,
and Python.

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

