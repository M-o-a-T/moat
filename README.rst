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
using cheap low-power microcontrollers and little or no bus attachment
hardware, on a possibly-unshielded random-topology cable, possibly with
walls that eat your WLAN for breakfast.

WLAN has problems: requires more power and doesn't go through the walls.
Also, radio is susceptible to random connectivity problems, dynamic mesh
radio is easy to get wrong and requires always-on nodes which again
requires too much power. Also, radio needs hardware.

A three-wire bus (1wire) is too fiddly to write clients for. (Several
people have tried.) Also, 1wire doesn't have multi-master and you don't
want to poll the bus all the time: 100 sensors eat too much power.

You could use half-duplex serial but there's the collision problem which
most UARTs are not equipped to handle. Your MCU might only have one serial
port which you'd rather use for uploads or debugging.

Next problem: long wires have somewhat high impedance, which limit your
transmission speed. You could use something like I2C but a software client
is annyoing to program and a hardware client is too susceptible to noise;
also, you need 16 bus transitions per byte. This is rather slow.

The MoaT bus offers a solution to all of this. It requires four wires:
ground, power, and two data lines. It adapts easily to more than two wires.
It is multi-master and does not require particularly accurate timers.


----------------------
Principle of operation
----------------------


A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information.

We still need to transmit binary data. The optimal message size on a
two-wire system ends up as 7 transitions which carry 11 bits of information
(log2(3^7)). Using three wires, we can send 14 bits with 5 transitions.
More than three wires are possible.

Since a message can contain excess bits, we can use an "illegal" sequence
to terminate the message. Bus messages thus don't need a length byte and
can be generated on the fly if necessary.

A small header carries addressing and a few bits of message type
information. All messages are terminated with a CRC. Every message must be
acknowledged.

The details are documented in ``doc/spec_wire.rst``.


----------
Addressing
----------

More than 100 devices on a single bus are not realistic, esp. when the bus
needs to supply power to all of them. Device addresses on the MoatBus thus
are 7 bits wide. More devices are possible with gateways.

Lots of communication flows between small dumb devices and some central
system. On the MoatBus there may be more than one of the latter, so the
server addresses get 2 bits. Server address 0 is reserved for
broadcast messages. Three "real" servers is sufficient for redundancy.

Short addresses are nice, but so is the ability to plug a new device into
the bus and have that device Just Work. Thus every device needs a MAC or
similar unique address; the client initially uses its MAC to request a bus
address from the master.


Message content
---------------

MoatBus devices shall be auto-discoverable. Each device carries a data
dictionary; if there's not enough ROM for it, the dictionary may be stored
on the server and referred to by name.

Access to all features of a device is mediated by the dictionary. It may
declare discoverable or even configurable shortcuts that can be used to
shorten bus messages and simplify firmware code.

The details are documented in ``doc/spec_message.rst``.


