=========
Rationale
=========

--------------
Why a new bus?
--------------

Given that RJ45, PoE, several VDSL options and multiple wireless options
exist, you might wonder why a new wired protocol might be useful.

The answer is that there is a rather large niche which doesn't have a good
solution. Assume, for the moment, that you want to deploy 100 sensors,
using cheap microcontrollers and little or no bus attachment hardware, on a
possibly-unshielded random-topology bus.

Sending data wirelessly works (there are enough protocols to do it, WLAN
Zigbee Bluetooth-BLE ZWave …) but that requires additional hardware.
Two-wire buses like KNX have the same problem. A three-wire bus like 1wire
is too fiddly to write clients for. (Several people have tried.) Anyway,
1wire doesn't have multi-master and you don't want to poll the bus all the
time.

You could use half-duplex serial but timing requirements are rather strong
(5%), and most built-in UARTs can't do half duplex. Also, your MCU might
only have one serial port which you'd rather use for debugging.

Thus, we're talking about a four-wire bus (or more, if you have spare wires
in your cable).

Next problem: long wires have somewhat high impedance, which limit your
transmission speed. You could use something like I²C, but a software client
is annyoing to program and a hardware client is too susceptible to noise.
Worse, you need 16 transitions per byte. This is rather slow.

The MoaT bus offers a solution to this problem. It requires four wires:
ground, power, and two data lines. It requires ~ five transitions per byte,
less if you have more than two wires. It is multi-master, self-timing, and
somewhat noise resistant.


Principle of operation
======================

A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information. (We could relax this and alternate 2^n-1
and 2^n, which helps somewhat, but at the price of significantly more
complexity.)

The bus chops each message into 11- or 14-bit chunks (depending on the
number of wires), treats the chunk as an unsigned number, encodes it to
base 2^n-1, adds one to each digit, and then successively XORs each digit
onto the wires. A CRC on the binary data helps prevent data corruption.

The end of a message is signalled by inverting every wire so often that the
resulting value would always overflow a 11- or 14-bit integer.


Bus addressing
==============

There' no point in catering for more than ~100 devices on a bus, mainly
because they all need to be powered. The MoaT bus thus limits its addresses
to 7-bit integers. Server systems get two bits. One address is reserved for
address assignment.

