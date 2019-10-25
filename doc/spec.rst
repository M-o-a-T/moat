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


Principle of operation
======================

A bus with N wires can assume 2^n states. The self-timing requirement
enforces *some* transiton between states, thus each time slot can transmit
log2(2^n-1) bits of information. (We could relax this and alternate 2^n-1
and 2-n, but as it turns out that doesn't help.)

We still need to transmit binary data. The optimal message size on a
two-wire system ends up as 7 transitions which carry 11.094 bits of
information (log2(3^7)). Using three wires, we can send 14.036 bits with 5
transitions. This seems rather optimal.

With even more wires, there's no longer an obvious best size that's
suitable for 8-bit CPUs. We'll settle on the fact that three transitions on
a four-wire bus carry 11.72 bits, while three transitions on a five-wire
bus carry 14.86 bits, which seems good enough.

..
   Requiring a transition on every second time slot would add lots of
   complexity and doesn't buy us that much: 12 instead of 11 bits on the
   2-wire bus, no advantage with more wires. Thus, we won't do that.


Bus Timing
++++++++++

Timer A is somewhat larger than the maximum signal round trip time on the
bus.

Timer B is the maximum delay allowed between "timer A expires" and "wire
state is sampled". This depends on the granularity of the participants'
timers, and on the interrupt latency for wire changes and
timer expiry.

Timer C is the timeout for collision recovery. Its initial value is A+B
(during a message) or 2A+B (transfer completed). It is started whenever
the bus is all-zero when timer A triggers.

Timer A controls both senders and receivers.

Timer B is only used when sending.

Timer C is used by any node which wants to send or receive a message.

At the beginning of each time slot, the sender pulls zero or more wires
low. It then starts timer A. Any receiver which notices a transition on
any bus wire also starts timer A. The sender re-starts A when it notices
any wire changes.

When the timer expires, the sender checks whether the bus is in the state
it should be. If it is not, a collision occurred. The sender will de-assert
its bus lines, wait until the bus is idle, and try again. Otherwise it will
start timer B; when that fires, the sender re-checks the wire state to
verify that all is still well, and sends the next piece of data by flipping
the state of at least one wire.

Receivers sample the bus when timer A expires, start timer C, then wait for
the next state change (at which time timer C is cancelled).

Senders start timer A when they change the wire state, verify that their
signal is on the bus when it expires, start timer B to ensure that all
receivers saw them, then start the next frame.

If the sender sees a wire change while timer B is running, the
transmission is aborted. Changes while timer A is running are mostly
ignored (except that when a wire gets asserted that should not be, there's
a collision) because the line impedance may cause transitions to occur long
after the sender changes its state.

Senders involved in a collision must switch to receiving.

Ideas for improvement
---------------------
The plan is to add a Measure command that determines round-trip parameters
between two nodes. Timers can then be tightened to adjust safety margins.

When there is no danger of collision (i.e. after the sender's address has
been transmitted), bus timing can be sped up.


Bus arbitration
+++++++++++++++

Initially the bus is idle: all lines are de-asserted.

A MoaT bus transition starts with a sender asserting one wire, according
to the packet's priority, and starting a timer that runs for A+B. If any
higher-priority wire is also asserted during that time, the sender must
immediately de-assert its signal and try again later.

The bus is idle when it is de-asserted for 2A+B. A sender waiting for a
slot will delay some random time between A and 3A before trying to transmit.


Collision detection
+++++++++++++++++++

Detecting a collision is easy: a wire is set which you don't want to be
set. The problem is quick recovery: we need to separate "sender A has set
wire 1, while sender B has set wire 2" from "sender B has set both wires".
This is important because if both senders notice the collision and drop
their signal, the next state is "no wire is set", which is *still*
indistinguishable from "sender B releases both wires" in the second case.

Thus there are two possible approaches to collision resolution:

* restrict the state space. The naïve way would disallow asserting more
  than one wire at a time, plus imposing ordering when de-asserting.
  This method would make transactions longer and the implementation
  significantly more complex in general, so its usefulness is limited to a
  highly-congested bus, which MoatBus should not be – that's why we're
  trying to speed up transmission, after all.

* Dropping off the bus, timing out as quickly as possible, and restarting
  in a controlled way.

This process can be sped up by causing immanent collisions as quickly as
possible.

Also, all messages carry both sender and recipient addresses so that late
collisions (i.e. in the message body the header) cannot happen.

Frame format
++++++++++++

The message to be transmitted is split into 11- or 14-bit frames. These are
interpreted as unsigned integers by repeatedly dividing them by 2^n-1. The
high end is sent first because that speeds up end-of-message detection when
using more than two wires.

header
------

* 1 bit: short destination address
* 2/7 bits: destination address
* 1 bit: short sender address
* 2/7 bits: sender address
* 2/5/8 bits: message type

The destination address is first because the receiver should be able to
determine as quickly as possible that a message is not intended for it.
This ultimately saves power.

After transmitting this header, collisions are a fatal error: the retry
algorithm used for quick collision resolution must not be used after
successfully receiving the first frame (or the second, when a
device-to-device message is sent).

The length of the message type is devised to byte-align the data.
Two bits are sufficient for server-to-server messages since they are able
to communicate via other channels anyway; client-to-client uses 8 bits so
that content (e.g. a temperature) can be associated directly, without further 
processing.

Data
----

* n bytes: message content.
  Interpreted per message type.
  To be specified elsewhere.

The receiver should store the message with an appropriate bit offset so
that the data end up byte-aligned.

Trailer
-------

* 1/2 bytes: CRC 8/16 (for n<8 / n>=8)

The data are protected by a CRC-8 if the actual message is less than 8
bytes, CRC-16 otherwise.

We use CRC-8-MAXIM and CRC-16-MODBUS algorithms because the devices they're
talking to are reasonably common in IoT, thus maybe you already have an
implementation using these parameters anyway.

9-byte messages are an error.

For the purpose of easily calculating the CRC with readily-available
library code, the two or three header bytes are padded with zero bits to
the next byte boundary. These filler bits are *not* transmitted.


End of message
--------------

A full (2-wire systems: triple; 3-wire: double) flip of all wires cannot
start a legal message. It is therefore used to signal its end.


* append checksum unless single-bit data
* repeat while the packet is not exhausted:
  * repeat for each 11- or 14-bit chunk (14 bit: message body for N=2/4):
    * clear flip sequence
    * repeat 7/5(4)/3/3 times (for N=2/3/4/5) (N=3: header requires 4 steps):
      * divide by (2^N-1)
      * add one
      * append to flip sequence
    * repeat until flip sequence is empty:
      * take the last entry
      * XOR that with the current state of the bus wires
      * set bus to the result
      * wait A+B
* Send end-of-packet sequence:
  * Twice (thrice for N=2):
    * set to ~(old_state)
    * wait A+B
  * Clear bus state
* Possibly wait for Ack packet

The first two frames are control frames. They are always 11 bit long, so
for N=3 we save a transition.

Each receiver will:

* wait for bus idle (unless expecting an Ack frame)
* wait until at least one wire is asserted
* wait Tbus
* if more than one wire is asserted:
  * wait until only one wire is asserted
  * if that doesn't happen for Tbus, abort
* fetch the first chunk
* check length and destination
* read L more chunks
* verify checksum

Fetching a chunk means
* set frame content to zero
* repeat 7/5/3/3 times (for N=2/3/4/5) header: 7/4/3/3):
  * multiply frame content by (2^N-1)
    (i.e. shift left 2^N and subtract old value)
  * read bus state
  * XOR with previous bus state
  * subtract one
  * add to frame
  * after s=2(N=2: 3) steps of this:
    * if frame == (2^N-1)^s -1:
      * end of frame: Process content.

Reading the bus state means:
* wait 5*Tbus for any change of signal
  * shouldn't be longer than 2*Tbus but this bus is self timed
  * None? aborted.
* wait Tbus
* read bus state

Packet format
+++++++++++++

A message consists of a header (one or two 11-bit frame) plus a
possibly-empty sequence of 11-bit (14-bit for 3-wire buses) frames which
are interpreted as bytes.

11 bits is not much, but sufficient to carry meaningful information. 

We'll assume that a bus has at most 128 participants, which requires 7
bits. We reserve one bit as a relay/extension bit, which MUST be
zero for now. Two bits are a sequence number. The last bit signals whether
this message is an original request (one) or a reply/ack (zero).

The next packet contains the sender address (again, 7+1 bits) plus a
function code (2 bits) and a "residual" bit which signals whether the last
complete byte of the last frame is valid (True if it is).

All packets are terminated with an 8-bit or 16-bit checksum; the latter is
used when the data length is >7 bytes. When calculating the checksum, the
initial 11-bit packes are extended to 16 bits, LSB first.

If the packets ends after the second 11-bit frame, the sender address is
interpreted as an 8-bit checksum (zeroed for the purpose of calculating
it).

Nonconforming packets are discarded.

Paket length encoding, collision detection
------------------------------------------

The data stream is terminated by a double (for two lines, triple) flip of
all wires on the bus, then clearing the bus. This pattern does not occur in
normal communication.

Collisions during data transfer are not signalled because there's no way to
detect whether the resulting wire state was intended by some other sender.
Instead, senders which notice a collision simply de-assert all lines and
stop transmitting. If the next state is all-off and there is no more
transition for another 4*Tbus, the message is deemed to be aborted.

The packet length is not encoded in the packet itself.

Addressing
++++++++++

The MoatBus is intended for devices which have a hardware ID (MAC, UUID,
manufacturer serial). Address assignment uses special recipient addresses.
A newly-connected participant must request a bus address. Waking up from
deep sleep may count depending on how long the address is valid.

Message sequencencing and acknowledgments
+++++++++++++++++++++++++++++++++++++++++

Each participant on the MoatBus has a unique 2-bit packet counter.

When originating a message, the counter is incremented and transmitted in
the first frame, with the Request bit set. A recipient must immediately
acknowledge the packet with a single frame to the sender (identical
counter, Request bit cleared). If the Ack packet is longer than one frame
or even contains data, the second frame's function code contains a
replacement sequence number which must in turn be used by the original
sender. This method is useful for three-way handshakes.

A one-frame packet with the Origin bit set is special: the address is
interpreted as a sender address and the two counter bits are used as
system codes.

+++++++++++++
Message Types
+++++++++++++

Depending on how long a message is and which header bits are set, MoatBus
messages carry different meanings.

The types are somewhat complex, esp. with CRCs stowed away in five
different places depending on the message's type and length. The reason for
this complexity is that (a) messages should be as short as possible, (b)
receivers must be able to determine that they can ignore a message as early
as possible (to save power) but (c) every message must carry at least a
CRC-8.

Saving power may not seem *that* important on a wired bus, but when 100
devices which require 50 mA at 5V all wake up at the same instant, you
suddenly need 25W of power …

Acknowledge
===========

Reception of a message *must* be acknowledged by sending a one-frame
response. The first 8 bits contain a CRC-8 of the original message,
the Request bit is clear, the Function bits mean

* 0: I got the message but I have a problem with it.

* 1: I did not check the message yet.

* 2: Message OK and acted upon, or no action necessary.

* 3: Message OK and not yet acted upon.

A Zero 

An Ack does not get acked in turn.

Fast Reply
==========

A piggy-backed Ack may have more than one frame. 

System codes
============

Single-frame messages with the Request bit set are special broadcast
messages. The destination address contains a CRC-8 of the remaining three
bits. The packet counter is re-purposed to mean:

0: This is a new master which lost state. Everybody please acquire a new address.

1: I have noticed excessive problems. Please reduce bus speed, i.e.
   increase the timer value.

2: extension

3: extension

CRC: in the recipient field.

This message is not ACK'd.

Function codes A
================

Two-frame packet, no data: Fast single-bit state change.

The "residual" bit is re-purposed to control whether to set or clear
one of four single-bit states. The state's number is in the function code bits.

This packet does not carry a sender address.

CRC: in the sender field.

Ack: see below.

Function A Acknowledge
======================

A Function Code A message is acked the usual way, except that the recipient
field is copied from the oiginal message's destination instead of its
source.

CRC: None, as in standard Ack messages.

Ack: None, obviously.


Function codes B
================

Directed frame with data. The Function codes of this frame are
device/application specific. The Request bit is set.

0: system inquiry and (auto)configuration

1: application A

2: application B

3: application C


Function codes C
================

Three-frame packet, Residual bit cleared: Fast single-value state change.

A message with one data frame and residual=False makes no sense since that
would result in an empty message which would carry no information.

The frame data is re-interpreted as to transmit one value [0…1] to one of 4
states. The state's number is in the function code bits. The upper 8 bits
of the value contain the message's CRC-8; for purpose of CRC calculation
the CRC bits shall be skipped and the 3/6-bit value left-padded to 8 bits.

Replies
=======

Reply mesages are formatted like Function Code B or C messages, with the
Request bit cleared. The function code is re-used to contain the (new)
reply sender's current sequence number.

Reply messages may serve as an ACK when piggy-backed to the original
request. If a reply is not ready in time, the recipient must send a normal
ACK immediately, and queue the reply (preferably with high priority) for
later delivery.

Unassigned Messages
===================

* One-frame non-piggybacked messages with Request cleared

* Two-frame messages with Request cleared

* Destination or source addresses >0x7F (does not apply when the
  address field in question is used to store a CRC-8)

Receivers may log, but must otherwise ignore, these messages. They must not
be sent.

++++++++++++++++++
Message priorities
++++++++++++++++++

The MoaT bus has N wires, thus may have up to N priority levels when
arbitrating the bus. In addition, the recipient address is transmitted
first and thus serves as a second-level arbitrator.

High-priority status should be given to

* replies, as they may block sender and recipient from releasing resources
  and/or re-using the sequence number

* action messages ("A switch has been thrown", "turn on the light") for
  immediately-visible changes, as the user experience is crucial.

* System messages

An additional set of (lower) priority levels is available simply by waiting
longer for a free bus. These should be used for

* address arbitration 

* long-term measurement data

The exact priority level of any given message (other than explicit ACKs) is
not part of this specification. We recommend to use high-priority messages
wisely.

ACK priority
============

Beside these levels, there's an "ultimate" priority level: sending an
immediate reply or ACK: these messages does not wait for bus arbitration.

This level must be used for ACKs, and may be used for replies if they're
ready in time. Long replies (defined as "uses a CRC16") should not use this
method.

A device must not piggyback a message onto one it originated. A sequence
of piggybacked messages should not be longer than three, including the
final ACK.

++++++++++++++++++
Address assignment
++++++++++++++++++

Bus address zero is used for requesting new addresses. The assignment
request packet will have both sender and recipient address zeroed, while
replies will carry a "real" sender address. The sequence number shall be
initialized randomly, incremented for each attempt.

Address assignment re-uses the Request bit to indicate that the sender
address is valid. If not, the sender field shall be either randomly
assigned (assuming that the sender has reasonably-random numbers at its
disposal), or set to the CRC-8 of the hardware address. The 8th bit shall
be cleared in either case.

Function codes:
+++++++++++++++

0: address assignment / verification

1: inquiry

2: extension

3: extension

Data
++++

Addressing messages consist of one byte (address to be assigned / verified,
top bit clear) plus N bytes (hardware serial / MAC). Unknown addresses
shall be zero. Unknown MACs shall not be transmitted.

When replying to a MAC-to-bus inquiry, the MAC is skipped. A negative reply
to an address verification or inquiry contains a zero address.


System inquiry
==============

MoatBus devices are supposed to be configurable. A device and its features
are described by short descriptive words with well-known meanings.

Device configuration and access looks like a very simple file system with
directories. The entries in each directory are numbered 0 to N-1; lookups
are done with offsets, not file names.

The first byte of an inquiry message contains the path length in the lower
four bits and a function code in the upper three:

0: Look up

1: read

2: write

All other codes are reserved.

Lookups result in one descriptive byte, and a length-prefixes name (UTF-8, but usually ASCII).

Bit 7: readable flag.
Bit 6: writable flag.
Bit 5: Enumeration. An additional byte follows that describes the number of
instances minus one.

If bits 6+7 are clear, the entry is a directory. Bits 4-0 encode the number
of entries. Otherwise they encode the number of bytes readable or writeable
to this file, plus one. A length of zero means that data for the entry must
always be prefixed by a length byte, while length 1 means that the data
fits in a nibble.

Read/write requires an additional byte for accessing the n'th member of an
enumeration after selecting it.

All path elements are encoded in one nibble. If an enumeration is expected
and the high bit is set, the rest of the nibble contains bits 6-4 while the
next one has the rest. There's no way to traverse the tree upwards.

As an example, consider the complete data dictionary of a four-port binary
I/O device::

    Lookup           Reply
    00               01 01 /

    10               02 06 system
    11               01 03 app

    20 00            81 08 busflags
    20 10            80 04 name
    20 20            80 03 MAC
    20 30            82 08 dev.code
    20 40            e0 03 08 markpath
    20 50            e0 04 08 funcpath

    21 00            22 03 04 port
    31 00            c1 05 drive      # 1=True
    31 01            c1 09 direction  # 1=out
    31 02            81 05 sense

Thus you could read the system name and device code with::

    12 01 13       => 07 Test123 \x12 \x34

or set port 3 to write an 1 output with::

    14 10 20 11 11

These bits, or rather nibbles, mean::

   1   write
   4   # of path elements
    1  app
    0  app/port
    2  app/port/3
    0  app/port/3/drive
   1   write 01 (High (probably))
   1   path elements (relative to previous)
    1  app/port/3/direction
   1   write 01 (out)
   -   end of data, we're done.

To shorten these paths even further, if you write the path "41 02 20" to
the third "funcpath" entry, a short two-frame packet with function code 3
will set or clear port 2. Assuming a baud rate of 10 kHz on a two-wire bus,
this would take 2.5 msec instead of ~8. By the same token
you can use the three "markpath" entries to point to local shortcut data.

Bus flags
---------

0: this system can handle multiple sub-paths in one message, as exemplified
   above

1: this system can do parent directories.

A missing bus flags direntry shall be assumed to be read as zero. Missing
markpath and funcpath entries mean that the corresponding feature does not
exist.

Unprovoked messages
-------------------

MoatBus devices don't send periodic messages unless you tell them to.
At the same time, polling is frowned upon. Thus you need to tell the
MoatBus device what to do.

To do that, a value should have "period" and "destination" entries.
"Period" is a two-byte unsigned (base unit: tenths of a second),
"destination" specifies the address and path which the value shall be
transmitted to.

Periodic checks can be done with "checkperiod" and "min"/"max" entries.
If the device notices that one of the limits is crossed it shall update the
value even if the "period" timer has not been reached.

Saving space
------------

If you do not have enough space in your ROM for all of this fancy directory
handling, you may let the root directory be a name instead. The server can
then extract the data from a file by that name. Please do not forget to
include a version number. Consider implementing shortcut access only, as a
server that can parse directories (or files representing them) is required 
to use them if they exist and contain the right values.

If you don't even have space for "proper" directory parsing, remove the
"busflags" entry (dropping the whole system subtree is not recommended),
hard-code the markpath and funcpath pointers, and make your hierarchy as
flat as possible. All function code prefixes would then fit in two bytes
which should be easily "parseable".

