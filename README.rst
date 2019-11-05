============
The MoaT bus
============

--------------
Why a new bus?
--------------

Given that RJ45, PoE, several VDSL options and multiple wireless options
exist, you might wonder why a new wired protocol might be useful.

The answer is that there is a rather large niche which doesn't have a good
solution. Assume, for the moment, that you want to deploy 100 sensors,
using cheap microcontrollers and little or no bus attachment hardware, on a
possibly-unshielded random-topology bus.

Data transfer using WLAN will not work because the sensors take too much
power. Bluetoothe BLE needs mesh topology which is easy to get wrong. Besides,
all wireless ideas need additional hardware. Two-wire buses like KNX have
the same problem. A three-wire bus like 1wire is too fiddly to write
clients for. (Several people have tried.) Anyway, 1wire doesn't have
multi-master and you don't want to poll the bus all the time. You could use
half-duplex serial but there's the collision problem, and your MCU might
only have one serial port which you'd rather use for debugging, and you
still can't use more than one wire.

Thus, we're talking about a four-wire bus (or more, if you have spare wires
in your cable).

Next problem: long wires have somewhat high impedance, which limit your
transmission speed. You could use something like I2C but a software slave
is annyoing to program and a hardware slave is too susceptible to noise;
also, you need 16 bus transitions per byte. This is rather slow.

The MoaT bus offers a solution to this problem. It requires four wires:
ground, power, and two data lines. It adapts easily to more than two wires.
It is multi-master and self-timing.


----------------------
Principle of operation
----------------------


A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information.

We still need to transmit binary data. The optimal message size on a
two-wire system ends up as 7 transitions which carry 11.094 bits of
information (log2(3^7)). Using three wires, we can send 14.036 bits with 5
transitions. This seems rather optimal.

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Our messages thus don't need a length byte and
can be generated on the fly if necessary.

A small header carries addressing and a few bits of message type
information. All messages are terminated with a CRC, which also serves to
determine whether the byte in the last frame is part of the message.

Every message must be acknowledged.

The details are documented in ``doc/spec_wire.rst``.


------------------------------
Addressing and Message Content
------------------------------

More than 100 devices on a single bus are not realistic, esp. when the bus
needs to supply power to all of them. Device addresses on the MoatBus thus
are 7 bits wide. More devices will be possible by forwarding.

Lots of communication flows between small dumb devices and some central
system. On the MoatBus there may be more than one of the latter, so the
master addresses get 2 bits. Master address 0 is reserved for
group-addressed messages. Three "real" master systems is sufficient for
redundancy.

Short addresses are nice, but so is the ability to plug a new device into
the bus and have that device Just Work. Thus every device needs a MAC or
similar unique address; one group address is thus reserved for address
assignment.

Message content
---------------

MoatBus devices shall be auto-discoverable. Each device carries a data
dictionary; if there's not enough ROM for it, the dictionary may be stored
on the server and referred to by name.

Access to all features of a device is mediated by the dictionary. It may
declare discoverable or even configurable shortcuts that can be used to
shorten bus messages and simplify firmware code.

The details are documented in ``doc/spec_message.rst``.

