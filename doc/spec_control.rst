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

  Bit 3 and 4 must be zero. other values are reserved for exchanging test
  data with the participating devices, to be specified.

* 7
  Reset
  The second byte contains a timer minifloat.
  Each device shall sleep some random time between X*timer and timer, where
  X is a fraction of that timer, as defined by the top three bits of the
  first byte. Then the device shall reset itself.

  If bit 3 is set, devices shall deep-sleep, i.e. use as little power as
  possible and not react to further bus messages. Otherwise they shall
  operate normally until "their" reset time arrives.

  If bit 4 is set, the message is extended with firmware-specific data: the
  next byte contains four flag bits (7…4) and a length-1 nibble (3…0)
  followed by the firmware revision. Only devices with this firmware shall
  reboot. Bit 4 asks the devices to switch to alternate firmware. Bits 7…5
  are reserved.


Poll request
============

Poll requests are used to check whether a client is (still) online. They
may contain online/offline timers as in AA requests. The intent is that the
AA request's timers are permanent, while times in Poll requests are
temporary and only apply until the next time a client resumes its online
state.

Client Ping
-----------

After completing address assignment or waking up, a client shall send a
Mode 4 (client broadcast) message.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client intends to be online. Zero tells the server that the client
is going off-line immediately; it should be sent (if possible) when a
client is disconnected by a third party, e.g. because of imminent loss of
power. 0xFF means "undetermined", used e.g. as long as a door is open.

If bit 3 is clear, the client assumes that it'll be online permanently.

If bit 4 is set, the next byte contains a timer minifloat that states
how long the client is likely to sleep before re-polling. Zero means
"indeterminate" (e.g. whenever somebody next opens a door) and is
equivalent to not setting this bit. 0xFF means "forever" and requires human
interaction (e.g. manually resetting the device) to revive the client.

Bits 5…7 are reserved.

Replies to a Server Scan or Server Ping are sent as Mode 5
(client-to-server) messages and have the same format.


Server Scan
-----------

A server scanning the bus for clients sends a Mode 3 message.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client should wait (maximally) until it does address assignment /
reporting. Otherwise clients shall wait until the bus is reasonably free.

Bits 4…6 select which clients should *not* answer. They are mutually
exclusive; bits 4…6 all being set is reserved.

Bit 4: clients that have a useable address (i.e. they have broadcast a
"Client Ping" message).

Bit 5: clients that don't have an address (i.e. they did not yet receive an
Address Assignment ACK).

Bit 6: Clients that did receive an ACK but did not yet send a "Client Ping"
message.

Bit 7: Another flag byte (bits 8…15) follows. If this is not set the other
flags are assumed to be zero.

Bit 8: Clients that are online permanently should not answer.

Bit 9: Clients that are online intermittently should not answer.

Bit 10: Clients whose online state is limited should not answer.

Bits 8…10 all being set is reserved. "Limited" means that the client will
go offline sometime, and if it does it'll stay offline. This state is used
for pre-configuration.

Bits 11…15 are reserved.


Server Ping
-----------

A server that checks whether a specific client is online sends a Mode 2 message.

If bit 3 is set, the next byte contains a timer minifloat that states how
long the client should listen before shutting down.

If bit 4 is set, the next byte contains a timer minifloat that states
how long the client may sleep before re-polling.

Bits 5…7 are reserved.

If the server sets a timer, the client is expected to use it; if it can do
so, its reply may skip echoing it. Otherwise it should reply with the
closest feasible value.

If the server does not set a timer, the client's reply is interpreted as in
"Client Ping", above.


Semantics
---------

A client must send a Client Ping after completing address assignment and internal
setup.

A client that's intermittently online typically sends a poll message
whenever it wakes up. If the wake-up was triggered by an event, it may
instead send that event's message.

Polled clients shall sleep some linearly-random time between zero and the
poll timer's value, then send their serial number (with Poll flag set) to
the requesting server. Client devices that don't yet have an address shall
use the timer's value to restart their address acquisition if it is not
still running.

A zero timer means "immediately" and should not be used with a
broadcast destination except when testing bus congestion handling.

A broadcasting client signals that it is awake. This should trigger
delivering all outstanding messages for it.


Console 
=======

This message type is used for debugging, error messages, and other text
data. It establishes a reliable bidirectional stream of possibly-packetized
bytes.

The packet loss recovery / flow control mechanism described here may be
re-used by other reliable channels (serial, I²C, etc.), though the process
of establishing the channel is necessarily different.

A client *should not* go to sleep while it carries channels with
non-acknowledged data.


Broadcast Mode
--------------

Until a connection is established, clients broadcast their console messages
(mode 4); the first byte contains a length byte-1, bit 7 is reserved, bit 6
is an incomplete-line indicator.


Channel Establishment
---------------------

A server that wants to establish a reliable console connection sends a Mode
2 message to the client. Flag bits:

* 3: take over

  If this bit is clear and there already is an established connection on
  this endpoint, the client will reply with an error.

* 4: reliable transmission

  If this bit is clear, messages are not protected.

  Unprotected channels do not transmit or receive Message Flow data.

  Channel setup APIs *must* use a tri-state flag to explicitly allow
  unprotected messages (yes / no / on-client-request). The default must be
  *no*. Clients and servers, on the other hand, must not unilaterally
  reject unprotected channels unless doing so would compromise real-world
  safety.

* 5: cancel

  If this bit is set, the console connection (or the attempt to set it up)
  is aborted.

* 6…7: reserved


The combination "reliable+cancel" indicates the passive end of a reliable
connection: the client shall acknowledge the connection and accept a
Connection Control message from the other end before proceeding.


The following two or three bytes contain data to identify and set up the channel.

One byte describes the command code on the client; the data dictionary
tells the server which command codes connect to which client subsystem.
If talking to a server, the top three bits are reserved.

The next one or two bytes point to the remote end which the client should
send to / receive from.

If bit 7 is clear, the remaining bits are the client address, followed by a
byte containing the remote end's command code (8 bits wide for client-to-client).

If bit 7 is set, bits 5+6 contain a server's address. (Both
being clear is reserved.) Bits 0…4 are the remote end's command code. A
value <4 is forbidden.

A "large" multi-function client may re-use the same command code for
multiple endpoints on different clients and/or servers. This ability
carries over to connection handling.


The client replies with a Mode 5 message if there is an error, *or* after
the connection is established.

Bit 3 in the client's reply indicates an error condition if set; bits 4…6
contain the error code:

* 0: unspecified

* 1: connection already established

* 2: command address is in use

* 3: timeout trying to set up the conection

* 4: destination command code is in use

* 5: no resources for reliable communication

* 6: not prepared to talk to a client

* 7: Negotiation error

If bit 7 is set, the message is followed by a length-1 byte (top two bits
reserved) and a human-readable error message.

If bit 3 is clear, setup was successful. Bits 5…7 are reserved.

A passive end reports success as soon as it is ready for the client to talk
to it.


Message Format
--------------

The first byte carries two flag bits.

If bit 7 is clear, the message contains data: the send number is
incremented. Bit 6 indicates whether the message is incomplete; the other
bits are interpreted as length+1, followed by message data.

Otherwise (i.e. bit 7 is set), this is a message flow (bit 6 is set) or
connection control (bit 6 is clear) control packet.


Text Data
---------

If a console channel transmits UTF-8 text, the first byte of each
(complete) message from the client *may* be used as metadata on the channel
that's used as a system console.

* Bits 7…6 must be 10: that's the tail of an UTF-8 sequence, which
  is otherwise illegal at the start of a message boundary.

* Bits 2…0 are used to indicate the error level
  (0:progress 1:trace 2:debug 3:info 4:warn 5:error 6:fatal 7:panic).

* Bits 5…3 may contain a client-specific subsystem code (sent from the
  client).

UTF-8 Glyphs *should not* be split between messages; UTF-8 characters *must
not* be split. Lines *should* be transmitted without terminating carriage
return or line feed whenever feasible: use bit 6 instead. Otherwise the
end-of line character shall be LF.

Progress messages are intended to replace a previous message with the same
subsystem code.

Messages to a client must be sent on an established channel and may not
contain metadata.

Message Flow
------------

Flow messages are sent when

* a flow message with bit 5 set is received

* an out-of-order message is received, indicating a missing message

* a recipient notices that the sender's buffer for transmitted messages is
  more than half full

* a recipient doesn't get more messages for some time: 1/2 second

* a sender didn't get an Ack for its last transmission(s) for some (longer)
  time: 1 second

Bit 5 is set if this message requests a Message Flow reply. A sender
transmits it if it didn't get an Ack for the last message it sent.

If bit 4 is clear, bits 0…3 count the number of messages the Ack's sender
didn't receive and which should be retransmitted. An example: if it receives
message 3 and then message 6 to 9, it'd send an ack for message 3,
indicating two outstanding messages. After getting 4 and 5 it'd then send
an Ack for message 9.

Otherwise (Bit 4 is set) the sender has run into an overflow condition,
i.e. there is data loss. Bits 0…3 count the number of messages lost, with
15=indeterminate. The sender should increment its sent-packet number before
sending this message. Transmission is halted. The remote side is expected
to acknowledge this message, echoing echos bits 0…3.

The second byte contains two nibbles: the last received message# from the
receiver in the top bits, plus a send counter. The send counter is
incremented when bit 7 is clear *or* bits 7 and 4 are both set.


Connection Control
------------------

The second byte, if present, is reinterpreted as the receive and send
buffer size, i.e. the number of possible outstanding messages.

If bit 5 is set, this is a connection rejection or tear-down. If bit 4 is
clear, bits 3…0 contain an error code, as above, and the second byte is
missing. Otherwise bit 3 is reserved and bits 2…0 encode the maximum
message length the sender expects to use, while the second byte
contains the limits the rejecter is prepared to accept.

Otherwise (i.e. bit 5 is clear) this is a connection set-up message. Bit 3
is reserved; bits 2…0 +1 encode the maximum incoming message length in
8-byte units -1, thus n=0 is 8 bytes and n=7 is 64 bytes. A following byte
contains two nibbles: the receive windo ẃ in bits 7…4 and the send window
in bits 3…0.

During setup, the active end sends a message with its parameters. The
passive end replies likewise. Send and receive window sizes are the smaller
of both sides.

Counters are initially zero; they're incremented before sending, thus the
first message each side sends to the other has a counter of 1. Clients must
store at least one message for repetition and *should* wait until the
earliest message is acknowledged instead of directly reporting an overflow.
Servers *must* wait.

