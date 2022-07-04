+++++++++++++++++
MoaT Bus messages
+++++++++++++++++

This document describes basic messaging on the MoaTbus.

Frame format
++++++++++++

After bus decoding, the message consists of one to three header bytes plus
any number of content bytes.

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

All messages should have a well-defined length, or carry their own length
indication if required. Violating this condition risks a higher probability
of falsely correct CRCs.


Addressing
++++++++++

The MoatBus is intended for devices which have a hardware ID (MAC, UUID,
manufacturer serial).

A newly-connected participant must request a bus address. Waking up from
deep sleep may or may not be considered "newly-connected", as the address
server(s) are expected to store known addresses permanently.

Bus-based address assignment is only used for clients. Servers are expected
to know their own address and to have other ways of communication among
themselves.

Reserved addresses
------------------

The message header has space for three servers and 126 clients.

Client addresses 0 and 127 are reserved.

The server address -4 is used for broadcast and multicast messages,
i.e. periodic measurements and events if they're of interest to multiple
clients, client polling, address assignment, etc..

In MoaT code server addresses are identified using negative integers
-1…-3, for addresses 3…1 (i.e. just add or subtract 4). The broadcast
address is written as -4.


Message priorities
++++++++++++++++++

A MoaT bus with N wires has up to N priority levels when arbitrating the
bus.

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
it is essential for quickly resolving bus conflicts.


+++++++++++++
Message Types
+++++++++++++

This table is to be interpreted top-down; the first match wins.

========  ===========  =======  ===========================
Source    Destination  Command  Type
========  ===========  =======  ===========================
Broadcast Broadcast    0        Mode 1; AA: request
Server    Client       0        Mode 2; AA: ACK
Server    Broadcast    0        Mode 3; AA: NACK
Client    Broadcast    0        Mode 4; AA: collision
Client    Server       0        Mode 5; AA: Poll Reply
any       any          0        reserved
Server    Client       1        data directory lookup
Client    Server       1        lookup reply
Client    Broadcast    1        alert (by data dictionary path)
Server    Client       2        data directory read                                              
Client    Server       2        read reply
Server    Client       3        data directory write
Client    Server       3        write reply
any       any          0…3      reserved
Broadcast Broadcast    1        Point-to-Point
Broadcast any          any      reserved
Client    Broadcast    any      broadcast message
any       any          any      direct message
========  ===========  =======  ===========================
Server    Server       0        inter-server sync
Broadcast Server       0        Serial flow control
========  ===========  =======  ===========================

Clients *must not* send with a source address that's not their assigned address.
Address Assignment request broadcasts (Mode 1) are the *only* exception.

Clients may not send command-zero broadcasts. Again, address collision
notifications are the sole exception.

Clients may receive broadcast messages from other clients, if so
configured, but any reply *must* be a randomly-delayed low-priority message.


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

Point-to-Point links
====================

MoaT messages can be transmitted on point-to-point links, e.g. a TTL serial
connection to a microcontroller. These links typically are somewhat
unreliable. 

Data dictionary
===============

MoatBus devices are (supposed to be) configurable, yet flexible; at the
same time they may have few resources and messages are required to be as
short as possible. This calls for a novel approach.

Device configuration and access looks like a very simple file system with
directories. The entries in each directory are numbered 0 to N-1; lookups
are done with these numbers, not names. Directory paths are nibbles,
i.e. four bits.

Lookups result in two bytes: one descriptive byte, four type bits, and a
length-minus-one-prefixed name (UTF-8, but usually ASCII), restricted to 16
bytes.

Directories cannot have zero or one entry. If required, a dummy "." entry
can be added.

===  ======================================================================
Bit  Use
===  ======================================================================
  7  readable?
  6  writable?
  5  numbered?
  4  Control
===  ======================================================================
     Directories (r,w are both zero)
3…0  Number of entries -2; 0xF is reserved
===  ======================================================================
     Files (r and/or w are set)
3…0  Type code
===  ======================================================================

File entries continue with a length nibble. See below.

If ``numbered`` is set, this directory consists of a number of "essentially
identical" entries or subdirectories, e.g. one describing I/O pins:
An additional nibble (or two, see below) with the number of instances
follows. That nibble may be zero if the feature is available but needs to
be dynamically configured.

For file names, the ``control`` bit states that the entry should be in
the control subdirectory. The default is data, or state+data for r/w
entries. On directories the flag instead states that its the entries should
be part of a data structure instead of being stored separately.

``numbered`` and ``control`` being both set is reserved.

The next nibble contains the length of the entry's name -1. It is followed
by padding to the next byte (if necessary) and an UTF-8 name.

If bits 6+7 are clear, the entry is a directory. Bits 3…0 encode the number
of sub-entries minus two. se while bit 4 encodes whether multiple requests are supported.

Directories don't get to have zero or one entries because you can just skip
the directory in that case. (Yes, this means that files can't be enumerated
on their own, but that's sufficiently uncommon.)

If bits 6 or 7 are set, the entry is a file. Bits 4…0 encode the number of
bytes readable or writeable, according to the table below.

Read/write requests to enumerated directories consume an additional nibble
or byte for accessing the specific member.

Writeable variable-length entries use another nibble/byte which states the
maximum length that can be written, minus one.

All path elements are encoded in one nibble. Enumerations may contain up to
128 entries (though they usually don't) by treating the high bit as an
extension marker:

=========  =============
Nibble(s)  Length
=========  =============
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
      F E  reserved
      F F  zero (so far)
=========  =============

There are no zero-length enumerations.

Directories must have 1…16 entries.

Data types are encoded with a four-bit typecode and a length nibble.

====== ============
Length Meaning
====== ============
   0   present
  ≤6   1…6 bytes
   7   8
   8   10
   9   12
  10   16
  11   20
  12   24
  13   32
  14   bit/nibble
  15   variable
====== ============

Variable-length data requires a length code nibble or two, as above.
"present" means that merely reading and/or writing the item is sufficient
to trigger an action (e.g. resetting a device, or polling the current
state).

The name of the root directory indicates the device type; if a device name
can be stored on it, the canonical location for that is ``sys.name``. A
directory length of 0xF indicates that this (sub)directory is not stored on
the client and should instead be retrieved from DistKV.

Typecodes with the high bit set generally indicate some control function.

======   ========  =================================
  Type     Length  Content
======   ========  =================================
  0000        var  UTF-8 (generic)
  0001        var  UTF-8 (concatenated)
  0100        var  binary (generic)
  0101        var  binary (concatenated)
  0110        var  binary (bits)
  1000        var  shortcut
  1010        var  broadcast dest+fn+timer+prefix
  1011        var  broadcast dest+fn+timer+prefix (missing last nibble)
  0000          0  dead entry (dummy, feature not present)
  0001          0  generic trigger
  0000     nibble  bool (1 is True, others >0 reserved)
  0001     nibble  bits
  0010     nibble  two bits
  0011     nibble  three bits
  0100     nibble  four bits, unsigned
  0101     nibble  signed -7…7 (0x8 is reserved)
======   ========  =================================
  0000      1,2,4  signed integer (MSB first)
  0001      1,2,4  unsigned integer (MSB first)
     *          4  -
     *          6  -
     *          8  -
     *         10  -
  0010        1,2  signed decimal (8+8)
  0011        1,2  unsigned decimal (8+8)
  1000          2  broadcast fn+timer
  1001          3  directcast dest+fn+timer
  0100          3  RGBL (5,6,5,8)
  0101          3  RGB
  0010          4  32-bit float
  0011          4  32-bit decimal (16+16)
  0100          4  RGBL (8,8,8,8)
  0101          8  geo coords (90-180/N1, 180-360/N2)
  0111          *  fixed-length bytes
  0101          *  fixed-length bits
     *          *  best effort
======  =========  ======  =================================

This type code system is designed to pass data unmolested. It's not really
comprehensive and doesn't try to describe all possible interpretations of a
value, but it tries to cover the most common interpretations.

"Concatenated" means that reading or writing multiple times appends data
instead of overwriting them (single entries; e.g. a serial console) or that
the data is too long and must be read iteratively (numbered; e.g. a file on
the device).

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

