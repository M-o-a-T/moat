========================
The MoaT-Command library
========================

Rationale
=========

MoaT contains some components which require a possibly bidirectional stream
of asynchronous messaging, including request/reply interactions and data
streaming.

This library supports such interactions.

Prerequisites
=============

The library requires a reliable underlying transport. MoaT uses CBOR, but
any reliable, non-reordering messsage stream that can encode basic Python
data structures (plus whatever objects you send/receive) works.

The MoaT-Cmd library does not itself call the transport. Instead it affords
basic async methods to iterate on messages to send, and to feed incoming
lower-level data in.


Usage
=====

.. code-block:: python

    from moat.util import packer, stream_unpacker

    async def handle_command(msg):
        if msg.cmd[0] == "Start":
            return "OK starting"

        if msg.cmd[0] == "gimme data":
            async with msg.stream_w("Start") as st:
                for i in range(10):
                    await st.send(i+msg.kw["x"])
                return "OK I'm done"

        if msg.cmd[0] == "alive":
            async with msg.stream_r("Start") as st:
                async for data in st:
                    print("We got", data)
            return "OK nice"

        raise ValueError(f"Unknown: {msg !r}")
        
    async with Transport(handle_command) as tr, anyio.create_task_group() as tg:
        decoder = stream_unpacker(cbor=True)

        def reader():
            # receive messages from channel
            async for msg in channel.receive():
                decoder.feed(msg)
                for m in decoder:
                    await tr.msg_in(m)

        def sender():
            # send messages to channel
            while True:
                msg = await tr.msg_out()
                await channel.send(packer(msg))

        def request():
            # streaming data in
            msg, = await tr.cmd("Start", x=123)
            print("Start", msg)
            async with tr.stream_r("gimme data") as st:
                print("They are starting", st.msg)
                async for msg in st:
                    print("I got", msg.args[0])
            print("They are done", st.msg)
            # may be None if they didn't send a stream

        def int_stream():
            # streaming data out
            async with tr.stream_w("alive") as st:
                print("They replied", st.args)
                i = 0
                while i < 100:
                    await st.send(i)
                    i += 1
                    anyio.sleep(1/10)
                await st.result("The end.")
            print("I am done", st.msg[0])
            
            
        tg.start_soon(reader)
        tg.start_soon(sender)
        tg.start_soon(handler)

        tg.start_soon(request)
        tg.start_soon(int_stream)


Specification
=============

MoaT-Cmd messages are encoded with CBOR.

All MoaT-Cmd messages are non-empty lists whose first element is a
small integer, identifying a sub-channel.

A transport that enforces message boundaries MAY send each message without
the leading array mark byte(s). If this option is not used or not
available, messages that are not arrays MAY be used for out-of-band
communication.

MoaT-Cmd messaging is simple by design and consists of a command (sent from
A to B) followed by a reply (sent from B to A). Both directions may
independently indicate that more, possibly streamed, data will follow. The
first and last message of a streamed command or reply are considered to be
out-of-band.

There is no provision for messages that don't have a reply. On the other
hand, an "empty" reply is just three bytes and the sender isn't required to
wait for it.

The side opening a sub-channel uses non-negative integers as channel ID.
Replies carry the ID's bitwise-negated value. Thus the ID spaces of both
directions are separate.

IDs are allocated when sending the first message on a sub-channel. They
MUST NOT be reused until final messages have been exchanged.

Exactly one final message MUST be sent in both directions.


Message format
++++++++++++++

A Moat-Cmd message consist of a preferably-small signed integer, plus a
variable and usually non-empty amount of data.

The integer is interpreted as follows.

* Bit 0: if set, the message starts or continues a data stream; if clear,
  the message is the final message for this subchannel and direction.

* Bit 1: Error/Warning.
  If bit 0 is set, the message is a warning or similar information and
  SHOULD be attached to the following command or reply. Otherwise it is an
  error.

All other bits contain the message ID, left-shifted by two bits. This
scheme allows for five concurrent messages per direction before encoding to
two bytes is required.

Negative integers signal that the ID has been allocated by that message's
recipient. They are inverted bit-wise, i.e. ``(-1-id)``. Thus an ID of zero
is legal. The bits described above are not affected by his inversion. Thus
a command with ID=1 (no streaming, no error) is sent with an initial
integer of 4; the reply uses -5.


Streaming
+++++++++

Data streams are inherently bidirectional. The command's semantics SHOULD
specify which side of a stream is supposed to send data. Error -2 will be
sent (once) if a streamed item is received that won't be handled.

Streaming may start when both sides have exchanged initial messages.
Sending a stream SHOULD NOT commence before the initial command has been
replied to.

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
messages it may transmit.

During stream transmission, the recipient then SHOULD periodically send some
more (positive) integers to signal the availability of more buffer space.
It MUST send such a message if the counter is zero (after space becomes
available of course) and more messages are expected.

The initial flow control messages SHOULD be sent before the initial command
or reply, but MAY be deferred until later.

A receiver SHOULD start flow control sufficiently early, but that isn't
always feasible. It MUST notify the remote side (error -5, below) if an
incoming message gets dropped due to resource exhaustion; likewise, the API
is required to notify the local side.

Error handling
++++++++++++++

The exact semantics of error messages are application specific.

Error messages with the streaming bit clear terminate the command.
They should be treated as fatal.

Error messages with the streaming bit set are either flow control
messages (see above) or warnings.


Known errors
------------

* -1: Unspecified

  The ``.stop()`` API method was called.

  This message MAY be sent as a warning.

  Usage: assume that a sender reads and transmits a block of ten
  measurements each second. If a "stop" warning arrives, the sender should
  complete the current block before terminating, while a "stop" error
  forces the current transmission to end immediately.

* -2: Can't receive this stream

  Sent if a command isn't prepared to receive a streamed reply.

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

  Sent if a command isn't prepared to handle a non-streamed request or
  reply.


* -11 …: No Command

  The command is not recognized.

  The error number encodes the command's position for a hierarchical lookup
  at the destination, i.e. if the command is ("foo","bahr","baz") and "foo"
  doesn't know about "bahr", the error is -12.


Examples
========

.. note::

    Legend:
    * D: direction / sign of message ID
    * S: Streaming
    * E: Error

= = = ====
S E D Data
= = = ====
- - + Hello
- - - You too
= = = ====

= = = ====
S E D Data
= = = ====
- - + Hello again
- * - Meh. you already said that
= = = ====

= = = ====
S E D Data
= = = ====
* - + gimme some data
* - - OK here they are
* - - ONE
* - - TWO
* * - Missed some
* - - FIVE
- - + Oops? better stop
* - - SIX
- - - stopped
= = = ====

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

= = = ====
S E D Data
= = = ====
* - + gimme some more data
* - - OK here they are
* - - NINE
* - - TEN
- * - oops I crashed
- - + *sigh*
= = = ====

= = = ====
S E D Data
= = = ====
* - + Let's talk
* - - OK
* - + *voice data* …
* - - *also voice data* …
- - + hanging up
- - - oh well
= = = ====

= = = ====
S E D Data
= = = ====
* * + 2
* - + gimme your database
* - - OK here they are
* - - A
* * + 1
* - - BB
* * + 1
* - - CCC
* - - DDDD
* * + 5
* - - EEEEE
* - - FFFFFF
* - - GGGGGGG
- - - that's all
- - + thx
= = = ====

