+++++++++++++++++
MoaT Bus messages
+++++++++++++++++

Frame format
++++++++++++

After bus decoding, the message consists of one to three header bytes plus
any number of content bytes. Excess bits ("padding") are ignored.

Header
------

* 1 bit: short destination address?
* 2/7 bits: destination address
* 1 bit: short sender address?
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

In the following text, devices with short addresses are commonly called
"master". Likewise, devices with long addresses are "slaves". This is used
as a shorthand for capability and function and does not imply that only
masters may initiate a bus transaction.

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
end-of-message. Since that is not 100% reliable and may pass shortened but
valid-looking messages that happen to pass the CRC check, higher levels
should verify that the message is not shortened.

Addressing
++++++++++

The MoatBus is intended for devices which have a hardware ID (MAC, UUID,
manufacturer serial). Address assignment uses special recipient addresses.
A newly-connected participant must request a bus address. Waking up from
deep sleep might be considered "newly-connected".

Reserved addresses
------------------

The message header has space for three masters and 126 slaves.

Slave addresses 0 and 127 is reserved for future expansion.

Master address 0 is used for multicast-ish messages, i.e. periodic
measurements (temperature, power, voltage, humidity) and events (motion,
door contacts), as well as address assignment.

Bus address assignment is only used for slaves. Master systems are expected
to know their address.


++++++++++++++++++
Message priorities
++++++++++++++++++

The MoaT bus has N wires, thus may have up to N priority levels when
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

Messages are initially classified by their address.

This table is to be interpreted top-down; the first match wins.

========  ===========  =======  ===========================
Source    Destination  Command  Type
========  ===========  =======  ===========================
Master 0  Master 0     random   Address assignment request
Master 0  Master X     any      reserved
Master 0  Slave        result   Address assignment response
Master X  Master 0     any      reserved
Slave     Master 0     any      broadcast message
any       any          0…3      data dictionary
any       any          any      direct message
========  ===========  =======  ===========================

Address assignment
==================

The payload for all address assignment messages starts with four flag bits
(reserved), four length bits, and that number of bytes +1 of device-specific
serial number, MAC, or other device-specific identifier.

Serial numbers longer than 8 bytes are reserved.

The result has the high bit set if there was an error.

* 0
  New address assigned.

* 1
  Old address found.

* 2…
  reserved

* 16
  No free address.

* 17
  Communication error, try again later.

* 18…
  reserved

Broadcast messages
==================

Slave devices may be configured, either statically or dynamically, to send
broadcast messages, either periodically or when specific events happen.

The details are described in the Data Dictionary specification, below.

Direct messages
===============

Slave devices may also be configured to send directed messages to other
devices. Direct messages should never be configured statically.

The details are described in the Data Dictionary specification, below.


Data dictionary
===============

MoatBus devices are (supposed to be) configurable. A device and its
features are described by short descriptive words with well-known meanings.

Device configuration and access looks like a very simple file system with
directories. The entries in each directory are numbered 0 to N-1; lookups
are done with these numbers, not file names. Directory paths are nibbles,
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
  5  Enumeration. An additional nibble/byte follows that describes the
     number of instances. May be zero if the feature is available but needs
     to be dynamically configured.
4…0  Number of entries
Files (r and/or w are set)
5…3  Type code
2…0  Length
===  ======================================================================

If bits 6+7 are clear, the entry is a directory. Bits 4…0 encode the number
of entries minus one; on the root directory, bit 4 encodes whether multiple
requests are supported.

If bits 6 or 7 are set, the entry is a file. Bits 4…0 encode the number of
bytes readable or writeable, according to the following table below.

Read/write requires an additional byte for accessing the n'th member of an
enumeration after selecting it.

All path elements are encoded in one nibble. Enumerations may contain up to
128 entries (though they usually don't) by treating the high bit as an
extension marker:

=========  ===========
Nibble(s)  Length
=========  ===========
        0  1
        1  2
        7  8
      8 0  9
      8 1  10
      9 0  25
        …  …
      F 7  128
      F 8  reserved …
      F F  reserved
=========  ===========

Directories must have 1…16 entries. The top level is restricted to at most
eight entries: if the high bit is set, the remaining three bits encode the
number of requests in this message, minus two. Support for this feature is
indicated by setting bit 3 of the number of entries of the top-level
directory.

Data types are encoded with two flag bits and three length bits. A length
of zero means either a length prefix or a nibble. A length of 5…7 is
interpreted as 6…10 because odd-byte data lengths are sufficiently rare.
Data >10 bytes must be prefixed.

======   ========  ======  =================================
  Type     Length  actual  Content
======   ========  ======  =================================
   000          0     var  UTF-8
   010          0     var  binary
   100          0     var  shortcut
   110          0     var  reserved
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
   101          2       2  broadcast dest+fn+timer (dest=0 usually)
   101          3       3  directcast dest+fn+timer (dest!=0)
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
    00               11 80 FourPort

    10               03 60 system
    11               00 30 app

    20 00            A9 50 flags
    20 10            80 40 name
    20 20            BD 30 MAC        # 6 bytes
    20 30            84 26 serial     # 32bit

    21 00            22 35 port
    31 00            C8 50 drive      # bool r/w
    31 01            C8 90 direction  # bool r/w
    31 02            88 50 sense      # bool r
    31 03            D2 80 shortcut   # quick access

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

There's no way to go up a directory, as that is seldom useful. One possible
exceptions are devices which offer "atomic" setting of more than one port
state. These should offer specialized entries for this function.


Unprovoked messages
-------------------

MoatBus devices don't send periodic messages unless you tell them to.
At the same time, polling is frowned upon. Thus, you need to tell the
MoatBus device what to do.

To do that, a directory entry may offer "broadcast" or "directcast"
entries. Their value consists of the destination device (for directcast),
the message code to use, and the timeout.

Periodic checks for exceeding limits can be done similarly. The suggested
feature is to add a "timer" byte and "min"/"max" entries. The timer shall
describe the period for checking the value; if it exceeds min or max the
destination shall be updated even if the broadcast / directcast timer has
not been reached. (The timer shall *not* be restarted.)

Timeouts are interpreted as an 8-bit unsigned minifloat with 4 exponent
bits, 4 mantissa bits, and no NaN interpretation, scaled so that 2 == 1
second. This affords a max timeout of 70 hours and an accurracy of +/- one
minute on a one-hour timeout, which should be more than sufficient.


Shortcuts
---------

A "shortcut" entry causes the slave in question to re-interpret the function
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
     D0 accessing function 0x10 writes to …
     1  path elements
     0  drive
     1  data
     0  filler nibble

then any access to function 0x10 of that device wil turn on port 2, no
messy path required.

Bit 7 controls whether the shortcut writes (True) or reads (False). Bit 6
signals (if True) that the last nibble in the shortcut data doesn't
actually exist. This is sometimes important when concatenating the
shortcut content with the data in the actual request.


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
reading should be done by a timer on the slave.

