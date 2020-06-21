============
The MoaT bus
============


+++++++++
Rationale
+++++++++


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
power. Bluetooth BLE needs mesh topology which is easy to get wrong. Besides,
all wireless ideas need additional hardware. Two-wire buses like KNX have
the same problem. A three-wire bus like 1wire is too fiddly to write
reliable clients for (several people have tried.) Also, 1wire doesn't have
multi-master and you don't want to poll the bus all the time. You could use
half-duplex serial but there's the collision problem, and your MCU might
only have one serial port which you'd rather use for debugging, and you
still can't use more than one wire.

Thus, we're talking about a four-wire bus (or more, if you have spare wires
in your cable).

Next problem: long wires have somewhat high impedance. This limits your
transmission speed. You could use something like I2C but a software client
is annoying to code and a hardware client is too susceptible to noise;
also, you need 16 bus transitions per byte. That seems rather slow.

The MoaT bus offers a solution to this problem. It requires four wires:
ground, power, and two data lines. It adapts easily to more than two wires.
It requires less than six bus clocks per byte.

-----------------
MoaT bus features
-----------------

The MoaT bus is designed to be a simple-to-implement, mostly-self-timing,
collision-resistant, error-resistant, multi-master bus system.

"Collision resistant" means that while the system tries to avoid
collisions, that is not always possible. However, the senders involved  
in a collision know how to resolve the problem so that one may proceed
quickly. Exponential back-off helps to prevent bus gridlock.  

"Error resistant" means that every packet is CRC-checked and must be 
acknowledged by the receiver.

"Multi-master" is a misnomer because there are no non-master systems on the
MoaTbus. Every node may send data to any other node when it wants to.

"Simple to implement": you only need a microcontroller with some free
open-collector binary ports and a somewhat-accurate timer. That's it.
Port change interrupts are optional; the timer doesn't need to trigger an
interrupt either. Messages are usually buffered but can be de/encoded on   
the fly – though the decoder must wait for the CRC before acting on any
message.

To explain "mostly self timing": contrast with an explicitly-clocked bus like
I²C. The sender may wait arbitrarily long before sending the next bit;
also, the receiver can even slow down the sender. Thus neither side needs
to observe any hard timing requirements. The downside is that a single line
is tied up for clocking, and you need two transitions per bit.

On the other hand, a serial line is implicitly-clocked: both sender and
receiver need to send / receive the next bit with an accurracy of 5% or
better. If sender or receiver have higher latency than that and can't use a
hardware UART, you're out of luck.
                                                                            
The MoaT bus takes the middle road. While there is a nominal baud rate,
the tolerance required for the timer is about 50%. The limiting factor is
the bus impedance.


Physical layer
==============

A bus with N wires can assume 2^n states. There is no clock, so we need
*some* transiton between states. Thus each time slot can transmit
log2(2^n-1) bits of information.

..
   Requiring a transition on every second time slot would add lots of
   complexity and doesn't buy us that much: 12 instead of 11 bits on the
   2-wire bus. Every third slot would reduce the 11-bit time to 6 slots but
   requiress a more accurate clock. There's no effect on a bus with more
   than two wires. Thus the (considerable) effort to implement this isn't
   warranted.

We still need to transmit binary data. The optimal block size on a
two-wire system ends up as 7 transitions which carry 11.094 bits of
information (log2(3^7)). Using three wires, we can send 14.036 bits with 5
transitions. This seems rather optimal.

All messages are protected by an 11-bit CRC, chosen because it fits into
one frame and adequately protects messages up to 100 bytes, which should be
sufficient for a low-speed bus.

The details are described in `doc/spec_wire`.

Link layer
==========

The MoaTbus assumes a maximum of three servers and ~120 clients on the bus.
Servers are assumed to be able to talk to each other off-line. Clients are
required to have a unique identifier (serial number, MAC, …). Server
address zero is used as a broadcast destination; clients 0 and 127
are reserved.

Thus we keep the header as short as possible:

* 1 bit: server destination address?
* 2/7 bits: destination address
* 1 bit: server sender address?
* 2/7 bits: sender address
* 2/5/8 bits: message type

The width of the message type is chosen to pad the header to the next byte
boundary. Fortunately this turns out to be sufficient.

The details are described in `doc/spec_link`.

Message format
==============

There is a design for data dictionary-based auto-discoverable message
semantics. This is in early stages and may or may not be actually
implemented.

The details are described in `doc/spec_message`.
