========================
The MoaT-Command library
========================

Rationale
=========

MoaT contains some components which require a possibly bidirectional stream
of asynchronous messaging, including request/reply interactions and data
streaming, possibly across system boundaries (but should be efficient on
same-system calls).

This library supports such interactions.

Prerequisites
=============

This library requires a reliable underlying transport for Python objects.
MoaT uses CBOR, but any reliable, non-reordering messsage stream that can
encode basic Python data structures (plus whatever objects you
send/receive) works.

The MoaT-Cmd library does not itself call the transport. Instead it affords
basic async methods to iterate on messages to send, and to feed incoming
lower-level data in.


Usage
=====

No transport
++++++++++++

.. code-block:: python

    from moat.lib.codec import get_codec
    from moat.lib.cmd import MsgEndpoint,MsgSender

    class Called(MsgEndpoint):
        async def handle_command(msg):
            if msg.cmd[0] == "Start":
                return "OK starting"

            if msg.cmd[0] == "gimme data":
                async with msg.stream_out("Start") as st:
                    for i in range(10):
                        await st.send(i+msg.kw["x"])
                    return "OK I'm done"

            if msg.cmd[0] == "alive":
                async with msg.stream_in("Start") as st:
                    async for data in st:
                        print("We got", data)
                return "OK nice"

        raise ValueError(f"Unknown: {msg !r}")

    srv=Called()
    client=MsgSender(srv)

    res, = await client.cmd("Start")
    assert res.startswith("OK")

    async with client.cmd("gimme data",x=5).stream_in(5) as st:
        async for nr, in st:
            print(nr)  # 5, 6, .. 14
        assert st.a[0] == "OK I'm done"

    async with client.cmd("alive").stream_out() as st:
        for i in range(3):
            await st.send(i)
        assert st.a[0] == "OK nice"

Using a transport
+++++++++++++++++

TODO


API Specification
=================

TODO


Transport Specification
=======================

All MoaT-Cmd messages are non-empty lists whose first element is a
small(ish) integer.

MoaT-Cmd messaging is simple by design and consists of a command (sent from
A to B) followed by a reply (sent from B to A).

There is no provision for messages that don't have a reply. On the other
hand, an "empty" reply is just three bytes and the sender isn't required to
wait for it.

The side opening a sub-channel uses a unique non-negative integer as
channel ID. Replies carry the ID's bitwise-negated value. Thus the ID
spaces of both directions are inherently separate.

IDs are allocated when sending the first message on a sub-channel. They
MUST NOT be reused until final messages (stream bit off) have been
exchanged in both directions. Corollary: Exactly one final message MUST be
sent in both directions.

Message format
++++++++++++++

A Moat-Cmd message consist of a preferably-small signed integer, plus a
variable and usually non-empty amount of data.

The integer is interpreted as follows.

* Bit 0: if set, the message starts or continues a data stream; if clear,
  the message is the final message for this subchannel and direction.

* Bit 1: Error/Warning.
  If bit 0 is clear, the message denotes an error which terminates the channel.
  Otherwise it is a warning or similar information, and SHOULD be attached
  to the following command or reply.

All other bits contain the message ID, left-shifted by two bits. This
scheme allows for five concurrent messages per direction before encoding to
two bytes is required.

Negative integers signal that the ID has been allocated by that message's
recipient. They are inverted bit-wise, i.e. ``(-1-id)``. Thus an ID of zero
is legal. The bits described above are not affected by this inversion. Thus
a command with ID=1 (no streaming, no error) is sent with an initial
integer of 4; the reply uses -5.


Streaming
+++++++++

Data streams are inherently bidirectional. The command's semantics SHOULD
specify which side is supposed to send data (originator, responer, or
both). Error -2 will be sent (once) if a streamed item is received that
won't be handled.

Streaming may start when both sides have exchanged initial messages.
Sending a stream SHOULD NOT commence before the initial command has been
replied to (with the Stream bit set).

Messages with both the streaming and error bits set carry out-of-band data
while the stream is open, e.g. advising the recipient of data loss.
Otherwise they MAY be delivered as warnings or similar out-of-band data.
Conceptally, these messages are attached to the command or reply that
immediately follows them.

For both directions, the initial and final message are assumed to be
out-of-band data. This also applies to warnings.

Flow Control
------------

For the most part: None. MoaT-Cmd is mostly used for monitoring events or
enumerating small data sets.

However, *if* a stream's recipient has limited buffer space and sends a
command that might trigger a nontrivial amount of messages, it MAY send a
specific warning (i.e. a message with both Error and Streaming bits set)
before its initial command or reply. This warning MUST consist of a single
non-negative integer that advises the sender of the number of streamed
messages it may transmit without acknowledgement.

During stream transmission, the recipient then MUST periodically send some
more (positive) integers to signal the availability of more buffer space.
It MUST send such a message if the counter is zero (after buffer space becomes
available of course) and more messages are expected.

The initial flow control messages SHOULD be sent before the initial command
or reply, but MAY be deferred until later.

A receiver SHOULD start flow control sufficiently early, but that isn't
always feasible. It MUST notify the remote side (error -5, below) if an
incoming message gets dropped due to resource exhaustion; likewise, the API
is required to notify the local side.


Error handling
==============

The exact semantics of error messages are application specific.

Error messages with the streaming bit clear terminate the command.
They should be treated as fatal.

Error messages with the streaming bit set are either flow control
messages (see above) or warnings.


Well-Known Errors
+++++++++++++++++

* -1: Unspecified

  The ``.stop()`` API method was called.

  This message MAY be sent as a warning.

  Usage: assume that a sender reads and transmits a sequence of ten
  measurements each second. If a "stop" warning arrives, the sender should
  complete the current block before terminating, while a "stop" error
  forces the current transmission to end immediately.

* -2: Can't receive this stream

  Sent if a command isn't prepared to receive a streamed request or reply
  on this endpoint.

* -3: Cancel

  The sender's or receiver's task is cancelled: the work is no longer
  required / performed.

  This message SHOULD NOT be transmitted as a warning;
  that would be pointless.

* -4: No Commands

  The sender on this side doesn't process commands at all.

* -5: Data loss

  An incoming message was dropped due to resource exhaustion (full queue).

  This message SHOULD be sent as a warning, but MAY be interpreted as a
  hard error by its receiver.

* -6: Must stream

  Sent if a command will not handle a non-streamed request or reply.

* -7: Error

  Used if the "real" error could not be encoded for some (equaly
  untransmittable) reason.

* -11 …: No Command

  The command is not recognized.

  The error number encodes the command's position for a hierarchical lookup
  at the destination, i.e. if the command is ("foo","bahr","baz") and "foo"
  doesn't know about "bahr", the error is -12.

  TODO

Other errors are sent using MoaT's link object encapsulation, i.e. the
error type (either a proxy or the name of the exception) followed by its
argument list and keywords (if present).

Examples
++++++++

.. note::

    Legend:
    * S: Streaming
    * E: Error
    * D: direction / sign of message ID

Simple command:

= = = ====
S E D Data
= = = ====
- - + Hello
- - - You too
= = = ====

Simple command, error reply:

= = = ====
S E D Data
= = = ====
- - + Hello again
- * - Meh. you already said that
= = = ====

Receive a data stream:

= = = ====
S E D Data
= = = ====
* - + gimme some data
* - - OK here they are
* - - ONE
* - - TWO
* * - Missed some
* - - FIVE
- - + [ 'OopsError' ]
* - - SIX
- - - stopped
= = = ====

Transmit a data stream:

= = = ====
S E D Data
= = = ====
* - + I want to send some data
* - - OK send them
* - + FOO
- - - Nonono I don't want those after all
* - + BAR
- * + OK OK I'll stop
= = = ====

Receive with an error:

= = = ====
S E D Data
= = = ====
* - + gimme some more data
* - - OK here they are
* - - NINE
* - - TEN
- * - [ 'CrashedError', -42, 'Owch', {'mitigating': 'circumstances'} ]
- - + *sigh*
= = = ====

Bidirectional data stream:

= = = ====
S E D Data
= = = ====
* - + Let's talk
* - - OK
* - + *chat data* …
* - - *also chat data* …
- - + hanging up
- - - oh well
= = = ====

Data stream with flow control:

= = = ====
S E D Data
= = = ====
* * + 2
* - + gimme your data
* - - OK here they are
* - - A
* * + 1
* - - BB
* * + 1
* - - CCC
* - - DDDD
      [ time passes until the originator has free buffer(s) ]
* * + 5
* - - EEEEE
* - - FFFFFF
* - - GGGGGGG
- - - that's all
- - + thx
= = = ====
