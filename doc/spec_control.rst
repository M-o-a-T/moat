Control messages
================

Control messages are defined as messages with a command byte of zero.
Every bus participant *must* read all control messages.

The message type is sent in the lower three bits of the message's first
byte. The other five bits contain control-specific flags.

Not all modes are defined for every control message type.

The following types are defined:

* 0
  Address Assignment

  See `doc/spec_aa.rst`.

  Unlike *all* other messages, a client must also process an AA message if
  it contains the client's MAC/serial. This includes messages to a
  "different" client.

* 1
  Poll

  See below.

* 2
  Console messages and setup

  See below.

* 3,4
  Reserved.

* 5
  Firmware update
  See `doc/spec_firmware.rst`.

* 6
  Bus test
  The second byte contains a timer minifloat.
  Between X/8*timer and timer, where X is the value of the top
  three bits of the first byte, some device will perform tests for bus
  timing or similar. Clients must ignore the bus during that time and must
  not try to send any messages.

  Only one test can be pending. A timer of zero (or a bus power-down)
  cancels a scheduled test; this obviously only works when the test time
  has not yet arrived.

  Bit 3 and 4 are reserved.

* 7
  Reset
  The second byte contains a timer minifloat.
  Each device shall sleep some random time between X*timer and timer, where
  X is a fraction of that timer, as defined by the upper three bits of the
  first byte. Then the device shall reset itself.

  If bit 3 is set, the devices shall deep-sleep, i.e. use as little power as
  possible and not react to further bus messages. Otherwise they shall
  operate normally until "their" reset time arrives.


Poll request
============

Client
------

A client that finishes registration or wakes up shall send a Mode 4 (client
broadcast) message.

The second byte contains a timer minifloat that specifies how long the
client will be online. 0xFF means "indefinite": the client will not
disconnect unless told to do so.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client intends to be online. Zero tells the server that the client
is going off-line immediately; it should be sent (if possible) when a
client is disconnected by a third party, e.g. because of imminent loss of
power. 0xFF means "undetermined" and is equivalent to not setting bit 3,
except that a client which doesn't set this bit doesn't expect to ever
disconnect in the first place.

If bit 4 is set, the next byte contains a timer minifloat that states
how long the client is likely to sleep before re-polling. Zero means
"indeterminate" (e.g. whenever somebody next opens a door) and is
equivalent to not setting this bit. 0xFF means "forever" and requires human
interaction (e.g. manually resetting the device) to revive the client.

Bit 5…7 are reserved.

Replies to a server scan or ping are sent as Mode 5 directed messages and have the
same format.

Server scan
-----------

A server scanning for clients sends a Mode 3 message.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client should wait (maximally) until it does address assignment /
reporting.

Bits 4…6 select which clients should *not* answer. They are mutually
exclusive; bits 4…6 all being set is reserved.

Bit 4: clients that have a useable address (i.e. they did broadcast a
"finished registration" message).

Bit 5: clients that don't have an address (i.e. they did not yet receive an
ACK).

Bit 6: Clients that did receive an ACK but did not yet send the "finished"
message.

Bit 7: Another flag byte (bits 8…15) follows. If this is not set the other
flags are assumed to be zero.

Bit 8: Clients that are online permanently should not answer.

Bit 9: Clients that are online intermittently should not answer.

Bit 10: Clients whose online state is limited should not answer.

Bits 8…10 all being set is reserved. "Limited" means that the client will
go offline sometime, and if it does it'll stay offline. This state is used
for pre-configuration.


Server ping
-----------

A server checking whether a specific client is online sends a Mode 2 message.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client should listen before shutting down.

If bit 4 is set, the next byte contains a timer minifloat that states
how long the client sleeps / may sleep before re-polling.

If bit 5 is set, the client shall not send a reply even if it is online.

Bit 6…7 are reserved.

Semantics
---------

A client that's intermittently online typically sends a poll message
when it has acquired its address / wakes up.

The/each client shall sleep some random time between zero and that timer's
value, then send its serial number (with Poll flag set) to the requesting
server. Client devices that don't yet have an address shall use the
timer's value to restart their address acquisition if it is not still
running.

A zero timer means "immediately" and should not be used with a
broadcast destination except when testing bus congestion handling.

A broadcasting client signals that it is awake. This should trigger
delivering all outstanding messages for it.


Console 
=======

This message type is used for debugging, error messages, and other text
data. It establishes a reliable bidirectional stream of possibly-packetized
bytes.

The packet loss recovery mechanism described here may be re-used by other
reliable channels (serial, I²C, etc.), though the process of establishing
the channel is necessarily different.

Until a connection is established, clients broadcast their console messages
(mode 4); the first byte contains a length byte-1, bit 7 is reserved, bit 6
is an incomplete-line indicator.

The first byte of each (complete) message may be used as metadata:
Bits 7…6 must be 10 because that's the tail of an UTF-8 sequence, which is
otherwise illegal at the start of a message boundary. Bits 0…2 are used to
indicate the error level (0:unknown 1:trace 2:debug 3:info 4:warn 5:error
6:fatal 7:panic) in the lower three bits. Bits 5…3 are reserved.

A server which wants to establish a console connection sends a Mode 2
message to the client. Flag bits:

* 3: take over

  If this bit is clear and the client already has a console connection,
  it will reply with an error.

* 4: reliable transmission

* 5: cancel

  If this bit is set, the console connection (or the attempt to set it up)
  is aborted.

* 6…7: reserved

The combination "reliable+cancel" indicates the passive end
of a reliable connection: the client shall wait for a message from the
other end before proceeding.

All messages are followed by two or three bytes.

* Destination. If bit 7 is set, the remaining bits are a client address,
  followed by a byte with the client command code (8 bits wide for
  client-to-client).

  If bit 7 is clear, bits 5+6 contain the destination server's address.
  (Both being clear is reserved.) Bits 0…4 are the destination command code.
  (0…3 is forbidden).

* the command which the client shall listen to, for incoming messages to
  this connection. If talking to a server the top three bits are reserved.


The client replies with a Mode 5 message if there is an error *or* after
the connection is established.

Bit 3 in the client's reply indicates an error condition if set; bits 4…6
contain the error code:

* 0: unspecified

* 1: connection already established

* 2: command address is in use

* 3: timeout trying to set up the conection

* 4: destination comman code is in use

* 5: no resources for reliable communication

* 6: not prepared to talk to a client

* 7: Negotiation error

If bit 7 is set, the message is followed by a length-1 byte (top two bits
reserved) and a human-readable error message.

If bit 3 is clear, setup was successful. Bits 5…7 are reserved. Note that a
passive end reports success as soon as it is ready for the client to talk
to it.


Message Format
--------------

The first byte carries two flag bits.

If bit 7 is clear, bit 6 indicates whether the message is incomplete;
the other bits are interpreted as length-1, followed by message data.

If the contents are UTF-8 text, glyphs *should not* be split between
messages; UTF-8 characters *must not* be split. Lines *should* be transmitted
without terminating carriage return or line feed (use bit 6 instead) if
possible – it might not be, as zero-length packets are not allowed.

Otherwise, this is a control packet.

If bit 6 is set, this is an Ack or Probe packet.

Bit 5 is set if the sender requests an Ack in return because it wants to
send more messages and/or its buffer is close to its limit.

If bit 4 is clear, bits 0…3 count the number of messages the Ack's sender
didn't receive and which should be retransmitted. I.e., if it received
message 3 and then message 6, it'd send an ack for two outstanding
messages.

Otherwise (Bit 4 is set) the sender has run into an overflow condition,
i.e. there is data loss. Bits 0…3 count the number of messages lost, with
15=indeterminate. The sender should increment its sent-packet number before
sending this message. Transmission is halted; it will resume when the
other side sends a similar ack with bits 0…3 set to zero. Any such Ack
*must* use the sender's packet number.

The second byte contains two nibbles: the last received message# from the
receiver in the top bits, and a send counter below.

Connection establishment
------------------------

If bit 6 is clear, this is a connection setup or "hard reset" message.

The second byte, if present, is reinterpreted as the receive and send
buffer size, i.e. the number of possible outstanding messages.

If bit 5 is set, this is a connection rejection or tear-down. If bit 4 is
clear, bits 0…3 contain an error code, as above, and the second byte is
missing. Otherwise bit 3 is reserved and bits 0…2 encode the maximum
message length the sender expects to use, while the second byte
contains the limits the rejecter is prepared to accept.

Otherwise this is a connection set-up message. Bit 3 is reserved; bits 0…2
+1 encode the maximum incoming message length.

The maximum message length is specified in 8-byte units -1, thus n=0
is 8 bytes and n=7 is 64 bytes.

During setup, the active end sends a message with its parameters. The
passive end replies likewise. Send and receive window sizes are the smaller
of both sides.

Counters are initially zero; they're incremented before sending, thus the
first message each side sends to the other has a counter of 1. Clients must
store at least one message for repetition and *should* wait until the
earliest message is acknowledged instead of reporting an overflow.
Servers *must* wait.

