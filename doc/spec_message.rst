+++++++++++++++++
MoaT Bus messages
+++++++++++++++++

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
  To be specified elsewhere.

The receiver should store the message with an appropriate bit offset so
that the data end up byte-aligned.

End of message
--------------

Messages do not carry a length indicator; bus framing is used to declare
end-of-message.

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

The server address -4 is used for multicast-ish messages, i.e. periodic
measurements (temperature, power, voltage, humidity) and events (motion,
door contacts), as well as address assignment.

Bus address assignment is only used for clients. Server systems are expected
to know their address.

In MoaT code, server addresses are identified using negative integers
-1…-4, for addresses 3…0 (i.e. add or subtract 4).

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

This table is to be interpreted top-down; the first match wins.

Reminder: the command is 2 bits wide for server-to-server messages, 8 bits
for client-to-client, and 5 bits otherwise.

========  ===========  =======  ===========================
Source    Destination  Command  Type
========  ===========  =======  ===========================
Broadcast Broadcast    0        Control 0; Address assignment request
Broadcast any          any      reserved
Server    Broadcast    0        Control 2; negative address assignment response
Server    Server       0        reserved (Control?)
Server    Server       any      inter-server sync
Server    Client       0        Control 1; positive address assignment response
Server    Client       1        data directory lookup
Server    Client       2        data directory read
Server    Client       3        data directory write
Client    Broadcast    0        Control 3; e.g. data request, console message, AA nack by clients
Client    Server       0        Control 4; replies (e.g. poll)
Client    Broadcast    1        alert (by data dictionary path)
Client    Server       2        read reply
Client    Server       3        write reply
any       any          0        reserved
Client    Broadcast    any      broadcast message
any       any          any      direct message
========  ===========  =======  ===========================

Clients must not send with any source address other than their own.
Address Assignment request broadcasts (Control 0) are the *only* exception.

Address assignment
==================

Address assignment messages are special control messages (see below): the
type is zero and the function code is reinterpreted as flag bit and four
bits for the length of the client's serial number / MAC / EUID, minus one.

Serial numbers longer than 16 bytes are not allowed. Serial numbers shorter
than 4 bytes are strongly discouraged.

If the flag bit is set, the request contains an additional flag byte after
the serial. Otherwise the flag byte is assumed to be zero.

The reply shall be identical to the sender's so that the receiver may
easily identify its reply.

The flag byte states:

* bit 0: wait. The next byte contains a timer minifloat.

  Request: I need this time before I can accept a reply.

  ACK: Wait this long before proceeding.

  NACK: Wait this long before trying again.

* bit 1: address is already known.

  Request: do not allocate a new address, just confirm me.

  ACK: I already know you.

  NACK: if request had bit 6 clear: No more free addresses. Try again after an address reset.
  NACK: if request had bit 6 set: No, I don't know you.

* bit 2: client is/shall be polled.
  This bit is set if/when the client wants to go to deep sleep, i.e. it will
  not listen to the bus. It should however wake up periodically, e.g. to
  read a sensor, and/or react on an external interrupt. 

  Do not set this just because you're answering a Poll request.

* bit 3: address is random.
  
  Request: this client just invented a new serial.

  ACK: Reserved.

  NACK: Collision. Sent by a client which saw its own serial in a request
  from somebody else. (The server sets bit 6 instead.)

The other bits are reserved.

A device with an empty serial number shall randomly invent one, primed by
observed bus timing if possible, and then send a request with bit 4
set. The server shall be extra cautious before assigning a new address to
this client.

Clients may monitor AA requests for their own serial. If the see a request
for it, they must NACK it with bit 4 set.

Control messages
================

For debugging or testing purposes it might make sense to reboot everything,
switch to an alternate medium like WiFi, poll which devices exist, or
otherwise reconfigure things.

Message types are carried in the first three bits of the message's first
byte. If applicable, the next five bits contain the destination code to send
replies to.

The following messages are defined:

* 0
  Address Assignment; see above.

* 1
  Poll

  If bit 0 is set, the next byte contains a timer minifloat that states how
  long the client should wait until it does address assignment / reporting.
  This is equivalent to the timer minifloat used in Address Assignment.

  Bit 1 and 2 have different meaning depending on whether bit 0 is on.

  If bit 0 is on:

  Bit 1 controls whether devices that already have an address should
  answer.

  Bit 2 is reserved.

  If bit 0 is off:

  If bit 1 is set, the next byte contains a timer minifloat that states how
  long the client declares itself to be / is supposed to be listening
  before shutting down.

  If bit 2 is set, the next byte contains a timer minifloat that states
  how long the client sleeps / may sleep before re-polling.

  Bit 3 and 4 are reserved.

  A client that's intermittently online typically sends one poll message
  when it has acquired its address / wakes up.

  Server>client, Server>broadcast:
  Address check if flag bit 0 is set.

  The/each client shall sleep some random time between zero and that timer's
  value, then send its serial number (with Poll flag set) to the requesting
  server. Client devices that don't yet have an address shall use the
  timer's value to restart their address acquisition if it is not still
  running.

  An empty address timer means "immediately" and should not be used with a
  broadcast destination.

  If flag bit 1 is set, the timer represents the minimum(!) time a polled
  device must be awake.

  If flag bit 2 is set, the timer represents the maximum(!) time a polled
  device may sleep.

  If the request is directed to a specific client and none of the flag bits
  are set, the client shall reply immediately.

  Client>broadcast:
  Tell the servers to send any data waiting for the client.
  Timer values 1 and 2 should be used to tell servers the actual time this
  client will be awake / sleeping. Sending a timer should be skipped if
  it's unchanged since the last wakeup.
  Timer 0 is reserved.

  Client>server:
  Reply to a server>client poll request.

* 2
  Console / serial port
  Client>server and server>client

  The second byte contains two nibbles: the last seen message# from the
  other side, plus a send counter.
  
  The third byte carries two flag bits and a length-1, followed by UTF-8
  text. Glyphs should not be split between messages; UTF-8 characters must
  not be split.

  If bit 7 is set the length instead contains the message# offset of the
  first missing packet (should be sent with high priority).
  If bit 6 is set the transmitted message# has been overflowing and the
  sender cannot wait for transmission to be fixed.

  If Bit 7 is set, bits 5 indicates that the channel shall be reset,
  communication buffers shall be cleared, and counters shall be set to
  zero. Bit 4 acknowledges a reset. If 7+5+4 are all set, the channel shall
  be considered dead; further messages will either be ignored or replied to
  with another message that has bits 7+5+4 set.

  Clients may have multiple independent ports, addressed by the lower 4
  bits of the function code in the first byte. Port 0 is reserved for
  commands and replies (think "serial console"). Port 1 is used for errors.
  Others may be e.g. a serial port connected to the client or messages
  carried by a radio protocol.

  Bit 4 of the function code, when set, indicates that the contents are
  incomplete and should be combined with the next message before being
  processed. Clients may, servers must support this.

  A server should log messages on channel 1. It may not reject them.

  Counters are initially zero; they're incremented before sending, thus the
  first message a side sends to the other has a counter of 1. Clients must
  store at least one message for repetition and should wait until the
  earliest message is acknowledged instead of reporting an overflow.
  Servers must do so.

* 5
  Firmware
  See separate document.

* 6
  Bus test
  The second byte contains a timer minifloat.
  Between X*timer and timer, where X is a fraction as defined by the lowest
  three bits of the first byte, some device will perform tests for bus
  timing or similar. Clients must ignore the bus during that time.
  Only one test can be pending. A timer of zero (or a bus reset) cancels a
  scheduled test; this obviously only works when the test time has not yet
  arrived.

* 7
  Reset
  The second byte contains a timer minifloat.
  Each device shall sleep some random time between X*timer and timer, where
  X is a fraction of that timer, as defined by the lowest three bits of the
  first byte. Then the device shall reset itself.

  Bit 3 is reserved.
  If bit 4 is set the devices shall deep-sleep, i.e. use as little power as
  possible and not react to further bus messages. Otherwise they shall
  operate normally until "their" reset time arrives.


Poll request
============

Some clients may not always be online. In this case a client shall send a
one-byte "poll request" message whenever it does listen to the bus. The
byte contains four flag bits (reserved) and a signed exponent n; the client
will listen for any messages during the following 2^n seconds, though it
should extend that time until the bus is idle sufficiently long for any
remaining messages to have been transmitted.

Broadcast messages
==================

Client devices may be configured, either statically or dynamically, to send
broadcast messages, either periodically or when specific events happen.

The details are described in the Data Dictionary specification, below.


Direct messages
===============

Client devices may also be configured to send directed messages to other
clients or servers. Direct messages must not be configured statically
because the address of the destination may change.

The details are described in the Data Dictionary specification, below.


Data dictionary
===============

MoatBus devices are (supposed to be) configurable, yet flexible; at the
same time they have few resources and messages are required to be as short
as possible. This calls for a novel approach.

Device configuration and access looks like a very simple file system with
directories. The entries in each directory are numbered 0 to N-1; lookups
are done with these numbers, not names. Directory paths are nibbles,
i.e. four bits.

Lookups result in one descriptive byte, four type bits, and a
length-minus-one-prefixed name (UTF-8, but usually ASCII), restricted to 16
bytes.

===  ======================================================================
Bit  Use
===  ======================================================================
  7  readable flag.
  6  writable flag.
Directories (r,w are both zero)
  5  Enumeration flag
  4  reserved, zero
3…0  Number of entries -2
Files (r and/or w are set)
5…3  Type code
2…0  Length, encoded
===  ======================================================================

If bits 6+7 are clear, the entry is a directory. Bits 4…0 encode the number
of sub-entries minus one; on the root directory, bits 3…0 are used for this
purpose while bit 4 encodes whether multiple requests are supported.

If bits 6 or 7 are set, the entry is a file. Bits 4…0 encode the number of
bytes readable or writeable, according to the table below.

The Enumeration flag states that this directory consists of a number of
"essentially identical" subdirectories, e.g. one describing I/O pins. An
additional nibble/byte with the number of instances follows. That nibble
may be zero if the feature is available but needs to be dynamically
configured.

Read/write requests to enumerated directories consume an additional nibble
or byte for accessing the specific member.

Writeable variable-length entries use another nibble/byte which states the
maximum length that can be written, minus one.

All path elements are encoded in one nibble. Enumerations may contain up to
128 entries (though they usually don't) by treating the high bit as an
extension marker:

=========  ===========
Nibble(s)  Length
=========  ===========
        0  1
        1  2
        …  …
        7  8
      8 0  9
      8 1  10
        …  …
      9 0  25
        …  …
      F 7  128
      F 8  reserved
        …  …
      F F  reserved
=========  ===========

Directories must have 1…16 entries. The top level is restricted to at most
eight entries: if the high bit is set, the remaining three bits encode the
number of requests in this message, minus two. The client indicates support
for this feature by setting bit 3 of the number of entries of the top-level
directory.

Data types are encoded with three flag bits and three length bits. A length
of zero means either a length prefix or a nibble. A length of 5…7 is
interpreted as 6…10 because odd-byte data lengths are sufficiently rare.
Data >10 bytes must be variable-length.

======   ========  ======  =================================
  Type     Length  actual  Content
======   ========  ======  =================================
   000          0     var  UTF-8
   010          0     var  binary
   100          0     var  shortcut
   110          0     var  broadcast dest+fn+timer+prefix
   001          0     1/2  bool (1 is True, others >0 reserved)
   011          0     1/2  nibble (unsigned)
   101          0     1/2  nibble (bits)
   111          0     1/2  nibble (reserved)
   000      1,2,4   1,2,4  signed integer (MSB first)
   001      1,2,4   1,2,4  unsigned integer (MSB first)
     *          4       4  -
     *          5       6  -
     *          6       8  -
     *          7      10  -
   010        1,2     1,2  signed decimal (8+8)
   011        1,2     1,2  unsigned decimal (8+8)
   101          2       2  broadcast fn+timer
   101          3       3  directcast dest+fn+timer
   100          3       3  RGBL (5,6,5,8)
   111          3       3  RGB (or anything else that wants three bytes)
   010          4       4  32-bit float
   011          4       4  32-bit decimal (16+16)
   101          6       8  geo coords (90-180/N1, 180-360/N2)
   111          *       *  list of bytes
   101          *       *  list of bits
     *          *       *  best effort
======  =========  ======  =================================

The type code on directories must be zero; all other values are reserved.

This type code system is designed to pass data unmolested. It's not really
comprehensive and doesn't try to describe all possible interpretations of a
value, but it tries to cover the most common interpretations.

All values extend over the whole range. For instance, a percentage should
be encoded as an unsigned byte with 50%=0x80, 100%=0xFF, instead of
100%=0x64.

As an example, consider the complete data dictionary of a four-port binary
I/O device::

    Lookup           Reply
    00               11 A0 FourPortThing

    10               03 50 system
    11               00 20 app

    20 00            A9 40 flags
    20 10            80 30 name
    20 20            BD 20 MAC        # 6 bytes
    20 30            84 50 serial     # 32-bit number

    21 00            22 33 port
    31 00            C8 40 drive      # bool r/w
    31 01            C8 80 direction  # bool r/w
    31 02            88 40 sense      # bool r
    31 03            D2 70 shortcut   # quick access

Thus you could read the system name and device code with::

    82 01 13      => 07 Test123 \x12 \x34

or set port 3 to write an 1 output with::

    84 10 20 11 11

These bits, or rather nibbles, mean::

   8   this message contains two paths
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

There's no way to walk back up.


Unprovoked messages
-------------------

As polling is generally a bad idea (it requires twice as many bus
messages), MoatBus devices send events or periodic measurements on their
own. This implies that the server needs to be able to tell them where to
send them to.

To do that, a directory entry may offer "broadcast" or "directcast"
entries. Their value consists of the destination device (for directcast),
the message code to use, and a timer.

Periodic checks for exceeding limits can be done similarly. The suggested
feature is to add a "timer" byte and "min"/"max" entries. The timer shall
describe the period for checking the value; if it exceeds min or max the
destination shall be updated even if the broadcast / directcast timer has
not been reached. (The timer shall *not* auto-restart when that happens.)

Clients are free to treat timeouts as very approximate guidelines; when the
server reads a timer, a client should reply with the value that best
approximates the timeout it actually uses.

Writing a timeout value (re)starts the accompanying timer.

Simple devices are free not to offer any writeable destinations and may
instead opt to simply broadcast the value in question with a pre-programmed
code. The data dictionary must be used to document this.

Directcast messages are always sent to another client. Their destination
must not be hard-coded or remembered across cold starts.

Minifloats
----------

MoaT wants to work with timers ranging from some large fraction of a second
(1/4th) to a day. That won't fit in 16 bits. Also, timeouts >1hr won't have
sub-second accurracy anyway.

Thus MoaT specifies timeouts unsing a minifloat, which is an 8-bit floating
point number (4 bits exponent, 4 bits mantissa, no sign – negative timeouts
don't exist). This number is scaled so that 1 equals to 1/4th of a second.

A minifloat can't accurately hit most full minutes, but if you need that
you can always undershoot your target and send a second smaller delay.
Since microcontroller sleep times tend to be rather inaccurate unless you
attach a real-time clock to them, that's a required strategy anyway.


Shortcuts
---------

Paths are fine for configuration but messy when actually using a device,
esp. when it only has a few functions. On the other hand, many function
codes are unallocated. Thus, the MoaT bus supports aliasing paths to
functions.

A "shortcut" entry causes the client in question to interpret the function
code written to the first byte of this entry as a read or write request
(depending on the 8th bit), relative to this directory, and appended with
the actual data.

As an example: if you write "41 01 33 90 10 10" to the device above, this
happens::

   4   # of path elements
    1  app
    0  port
    1  Port 2
    3  shortcut
    3  we write 3 bytes
     90 accessing function 0x10 writes to …
     1  path elements
     0  drive
     1  data
     0  filler nibble

then any access to function 0x10 of that device wil turn on port 2, no
messy path analysis (and in fact no data) required.

Bit 7 controls whether the shortcut writes (True) or reads (False). Bit 6
signals that the last nibble in the shortcut data doesn't actually exist.
This is sometimes important when concatenating the shortcut content with
data in the actual request. Bit 5 is reserved.

The server is required to read all shortcut entries. It must use the
shortcut with the longest possible prefix when accessing a client.
This ensures that a space-limited client may publish a regular data
dictionary but doesn't need to implement actual directory path walking.

Shortcuts are used only when a server sends a message to a client; they're
otherwise treated exactly like ordinary "read" or "write" messages.
Replying to a "read" uses the normal "reply" function code 3.


Saving space
------------

If you do not have enough space in your ROM for all of this fancy directory
handling, the root directory might have the name of your device. The only
visible directory entry might be a file named "v" which contains the
firmware version number. The server can 

Even more radically, most or even all feaures of your device might be
accessible via the shortcut mechanism. You don't need to actually implement
any shortcut handling because the server is required to use a shortcut if
it knows about it -- and you can hard-code the shortcut data in your config
file.


Replies
=======

Reply messages are sent to whichever device originated a request, code
0x03. The sender associates them with its request by virtue of their
addresses. The MoaT bus does not use message sequence numbers. There should
not be more than one outstanding read request. In fact, after setting up
everything there should be no read requests whatsoever – any periodic
reading should be done by a timer on the client.

