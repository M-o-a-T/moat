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

This document describes all messages of code zero. Messages with that
typecode which are not mentioned here are reserved. Messages with other
codes are described elsewhere.

========  ===========  =======  ===========================================
Source    Destination  Command  Type
========  ===========  =======  ===========================================
Client 0  Server 0     0        address assignment request
Server 0  Client X     0        positive address assignment response
Client 0  Server X     0        negative address assignment response
--------  -----------  -------  -------------------------------------------
Server X  Client 0     0        all-client system control messages
Server X  Client X     0        specific-client system control messages
Server X  Server X     0        ping request (x != y) / keepalive (x == y)
Server X  Server 0     0        DistKV sync
--------  -----------  -------  -------------------------------------------
Client X  Server 0     0        poll, console (from client) 
Client X  Server X     0        specific-client replies
========  ===========  =======  ===========================================

Source/Destination of address assignment messages are used mainly for
disambiguation and don't otherwise "mean" anything. Devices with an address
shall not react to AA messages. Devices without an address shall react on
messages addressed to Client 0.

Address assignment
==================

The payload for all address assignment messages starts with four flag bits,
four length bits, and that number of bytes +1 of device-specific serial
number, MAC, or other device-specific identifier. Serial numbers longer
than 16 bytes are not allowed as we don't need to number every grain of
sand on the planet. Serial numbers shorter than 6 bytes are strongly
discouraged because the likelihood of collisions is too high.

Request
-------

* Bit 3 indicates that this address is to be released, not acquired.
  Sent by a device that has its firmware changed, or a server that could
  not reach the device for a long time, or ….

  If this bit is set, the other three are reserved.

* Bit 2 marks the client as a low-power system that doesn't listen for
  commands all the time, i.e. it can only be talked to some time after
  receiving a "poll" message. 

* Bit 1 states that the device has incomplete firmware. It started up
  in boot loader mode.

* Bit 0 is reserved.

The result message uses a four-bit status code field. The rest of the data
shall be identical to the sender's so that the receiver may easily identify
its reply.


Positive response
-----------------

* Bit 3 is set if this assignment refers to an existing mapping. If it is
  zero, the device may expect some interrogatory messages / should tell the
  server about its capabilities / should clear any automatic transmission
  until (re-)instructed to do so by the server.

* Bit 2 states that the device must stay in system/bootloader mode.
  
  The server must set this bit when the request has bit 1 set.

* Bits 1…0 are reserved.


Negative response
-----------------

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
  Can only be addressed to all clients.
  
* 1
  Console input
  Assuming that the device contains some sort of command interpreter, send
  the message in the following bytes to it.
  Can only be addressed to a specific client.

* 2
  Firmware update.
  TODO see separate document.
  The "firmware version" subcommand may be sent as a broadcast.

* 3…12
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


Client broadcasts
=================

The first byte contains a 4-bit type code and a type-specific value SV.

The following types are defined:

* 0
  Poll

  Some clients may not always be online. In this case a client shall send a
  one- or two-byte "poll request" message whenever it does listen to the
  bus. SV contains a signed exponent n; the client will listen for messages
  during the following 2^n seconds, though it should extend that time until
  the bus is idle sufficiently long for any remaining messages to have been
  transmitted.

  The next byte, if present, contains a timer minifloat which tells the
  server approximately how long the client will be unavailable after it
  disconnects.

  "Normal" messages sent by a polling client do not imply that the client is
  reachable.

* 1
  Console

Specific-client replies
=======================

The first byte contains a 4-bit type code and a type-specific value SV.

The following types are defined:

* 0
  Poll reply
  Content: serial number, as in address assignment request.
  The SV is the length.

* 1

* 2
  Firmware update ack
  TODO separate document

* 3
  Firmware update reject
  TODO separate document

