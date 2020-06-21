+++++++++++++++++++
MoaT Bus link layer
+++++++++++++++++++

This document describes basic messaging on the MoaTbus.

Frame format
++++++++++++

After bus decoding, the message consists of one to three header bytes plus
any number of content bytes. Excess bits ("padding") are ignored.

Header
------

* 1 bit: server destination address?
* 2/7 bits: destination address
* 1 bit: server sender address?
* 2/7 bits: sender address
* 2/5/8 bits: message type

The destination address is first because the receiver should be able to
determine as quickly as possible that a message is not intended for it.
This ultimately saves power.

In the following text, devices with short addresses are commonly called
"server". Likewise, devices with long addresses are "clients". This is used
as a shorthand for capability and function and does not imply that only
servers may initiate a bus transaction.

Data
----

* n bytes: message content.
  Interpreted per message type.

Addressing
++++++++++

The MoatBus is intended for devices which have a hardware ID (MAC, UUID,
manufacturer serial). Address assignment uses special recipient addresses.
A newly-connected participant must request a bus address. Waking up from
deep sleep might be considered "newly-connected".

Reserved addresses
------------------

The message header has space for three servers and 126 clients.

Client addresses 0 and 127 are reserved for future expansion.

Server address 0 is used for multicast-ish messages, i.e. periodic
measurements (temperature, power, voltage, humidity) and events (motion,
door contacts), as well as address assignment.

Bus address assignment is only used for clients. Server systems are expected
to know their address, as they should be connected via IP (or whatever)
anyway.

Message priorities
++++++++++++++++++

A MoaT bus with N wires may have up to N priority levels when
arbitrating the bus.

High-priority status should be given to

* replies, as they may block sender and recipient from releasing resources
  and/or re-using the sequence number

* action messages ("A switch has been thrown", "turn on the light") for
  immediately-visible changes, as the user experience is crucial.

* System messages

An additional set of lower priority levels is available simply by waiting
longer for a free bus. These should be used for

* address arbitration 

* long-term measurement data

The exact priority level of any given message is not part of this
specification. We recommend to use high-priority messages wisely.

NB: Messages lose their priority as soon as they're involved in a
collision. While this mechanism may delay high-priority messages somewhat,
it is essential for quickly resolving conflicts.


+++++++++++++
Message Types
+++++++++++++

This document implements messages of typecode zero. All others are
application defined.

========  ===========  =======  ===========================
Source    Destination  Command  Type
========  ===========  =======  ===========================
Server 0  Server 0     0        address assignment request
Server 0  Client       0        positive address assignment response
Server 0  Server X     0        negative address assignment response (from server X)
Server X  Server 0     0        all-client system control messages
Server X  Client       0        specific-client system control messages
Client    Server 0     0        poll (from client)
Client    Server X     0        poll request (from server X)
Client    Client       0        reserved
========  ===========  =======  ===========================

Address assignment
==================

The payload for all address assignment messages starts with four flag bits,
four length bits, and that number of bytes +1 of device-specific serial
number, MAC, or other device-specific identifier. Serial numbers longer
than 16 bytes are not allowed. Serial numbers shorter than 4 bytes are
strongly discouraged.

Flags:
* Bit 0 marks the client as a low-power system that doesn't listen for
  commands all the time, i.e. it can only be talked to some time after
  receiving a "poll" message. 
* Bits 3…1 are reserved.

The result message uses a four-bit status code field. The rest of the data
shall be identical to the sender's so that the receiver may easily identify
its reply.


Positive status codes:

* Bit 3 is set if this assignment refers to an existing mapping. If it is
  zero, the device may expect some interrogatory messages / should tell the
  server about its capabilities / should clear any automatic transmission
  until (re-)instructed to do so by the server.

* Bits 2…0 are reserved.


Negative status codes:

* If bit 3 is clear: client problem.
  * if bit 2 is set: the server is incompatible with one of the client flags 
    * bit 1+0 (as a 2-bit integer) tell which flag
  * bit 2 clear: reserved
* Otherwise: server-side problem
  * bit 2 clear: server can't reply right now
    * bit 1+0 say when to retry:
      00 - ten seconds
      01 - ten minutes
      10 - until a Poll or Address Acquire command
      11 - reserved
  * bit 2 is set: client should power down
    * bit 1+0 say for how long, approximately:
      00 - an hour
      01 - a day
      10 - a week
      11 - forever

There currently are no flag bits defined.

Negative replies 

The server will clear any flags which it doesn't understand.

All/Specific Client messages
============================

Message types are carried in the upper four bits of the first byte.

The following messages are defined:

* 0
  Poll
  The second byte contains a timer minifloat.
  Each device shall sleep some random time between zero and that timer's
  value, then send its serial number (same format as an Address Assignment
  request) to the requesting server. Devices that don't yet have a client
  address shall also wait that random time, then acquire one, then send
  their reply.

* 1
  Address Acquire
  Like 0/Poll, but only devices that don't have an address should react.
  Can only be addressed to all clients; its meaning for specific clients is
  reserved.

* 2…12
  Reserved

* 13
  Bus timing change
  The second byte contains a timer minifloat. The third and fourth byte
  hold the number of microseconds for tB, the fifth states which fraction
  of tB the value of tA should be.
  Between X*timer and timer, where X is a fraction as defined by the lowest
  four bits of the first byte, bus timing should be changed to the given
  value.
  If X is zero, the change applies when the timer runs out and shall be
  permanent.

* 14
  Bus test
  The second byte contains a timer minifloat.
  Between X*timer and timer, where X is a fraction as defined by the lowest
  four bits of the first byte, some device will perform tests for bus
  timing or similar. Clients must ignore the bus during that time.
  Only one test can be pending. A timer of zero (or a bus reset) cancels a
  scheduled test.

* 15
  Reset
  The second byte may contain a timer minifloat.
  The device shall sleep some random time between X*timer and timer, where
  X is a fraction of that timer, as defined by the lower three bits of the
  first byte. Then the device shall reset itself.
  Bit 3 is a "hard reset" flag: the device shall return to whatever passes
  for factory settings.


Polling
=======

Some clients may not always be online. In this case a client shall send a
one-byte "poll request" message whenever it does listen to the bus. The
byte contains four flag bits (reserved) and a signed exponent n; the client
will listen for any messages during the following 2^n seconds, though it
should extend that time until the bus is idle sufficiently long for any
remaining messages to have been transmitted.

The next byte, if present, contains a timer minifloat which tells the
server approximately how long the client will be unavailable after it
disconnects.

"Normal" messages sent by a polling client do not imply that the client is
reachable.

A server may send a "poll request" message with the same semantics, asking
the client to use that time / these times instead. The client shall reply
with another Poll message that approximates the times it'll actually use as
accurately as possible.

Clients that do not require polling must not react to these messages.
