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

:: python

    from moat.util import packer, stream_unpacker

    async def handle_command(msg):
        if msg.cmd[0] == "Start":
            return "OK starting"

        if msg.cmd[0] == "gimme data":
            async with msg.stream_w("Start") as st:
                for i in range(10):
                    await st.send(i+msg.data["x"])
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
            msg = await tr.cmd("Start", x=123)
            print("Start", msg)
            async with tr.stream_r("gimme data") as st:
                print("They are starting", st.msg)
                async for msg in st:
                    print("I got", msg)
            print("They are done", st.msg)
            # may be None if they didn't send a stream

        def int_stream():
            # streaming data out
            async with tr.stream_w("alive") as st:
                print("They replied", st.msg)
                i = 0
                while i < 100:
                    await st.send(i)
                    i += 1
                    anyio.sleep(1/10)
                st.msg = "The end."
            print("I am done", st.msg)
            
            
        tg.start_soon(reader)
        tg.start_soon(sender)
        tg.start_soon(handler)

        tg.start_soon(request)
        tg.start_soon(int_stream)


Specification
=============

All messages are non-empty lists whose first element is a small(ish)
integer. Messages that don't match this description MAY be used for
out-of-band communication.

A transport that enforces message boundaries MAY send each message without
the leading array mark byte(s).

MoaT-Cmd messaging is simple by design and basically consists of a command
(sent from A to B) followed by a reply (sent from B to A). Both directions
may independently indicate that more, streamed data will follow. The first
and last message of a streamed command or reply are considered to be
out-of-band.


Message format
++++++++++++++

A Moat-Cmd message consist of a preferably-small signed integer, plus a
variable and usually non-empty amount of data.

The integer is interpreted as follows.

* Bit 0: if set, the message starts or continues a data stream; if clear,
  it either ends a stream or consititues a standalone reply.

* Bit 1: Error/Warning.

All other bits contain the message ID, left-shifted by two bits. This
scheme allows for five concurrent messages per direction before encoding to
two bytes is required.

Negative integers signal that the ID has been allocated by that message's
recipient. They are inverted bit-wise, i.e. ``(-1-id)``. Thus an ID of zero
is legal. The bits described above are not affected by his inversion. Thus
a command with ID=1 (no streaming, no error) is sent as ID=4, the reply
gets ID=-5 (likewise).

Thus, for incoming messages, non-negative IDs indicate replies.

Error handling
++++++++++++++

The exact semantics of error messages are application specific.

An error that terminates a stream SHOULD be considered a fatal condition.
It MUST interrupt a stream that travels in the opposite direction, though
(due to the asynchronous nature of the data stream) late messages may still
show up. These SHOULD be ignored.

If both bits are set, handling the message is somewhat more complex; the
basic rule is that an error cannot start a data stream. Thus:

* is this the first message on this stream? yes: ignore.
* did the sender close its side of the conversation? yes: error
* otherwise: interpret as a warning

This is required because a sender might terminate its side of the
conversation, but it should still be able to interrupt the other side
*and* such an interrupt must not interfere with the next command
if the stream was closed, and the next command re-uses the ID,
while the error message was in transit.

This library may generate internal errors and send them to the remote side,
e.g. if the remote side replies to a simple command with a streaming-start
message. They are encoded as small negative numbers without further data.
Other errors are currently returned as (typename,args) tuples.
(TODO: add an option to send proxied exceptions.)

Known errors
------------

* -1: Unspecified
  Somebody called ``.stop()`` without further elucidation

* -2: Can't receive this stream
  Sent if a command isn't prepared to receive a streamed reply.

* -3: Cancel
  The sender's or receiver's task is cancelled: the work is no longer
  required.



Examples
========

.. note::

    Legend:
    * D: direction / sign of message ID
    * 0/1: Bits

= = = ====
0 1 D Data
= = = ====
0 0 + Hello
0 0 - You too

0 0 + Hello again
0 1 - Meh. you already said that

0 0 + gimme some data
1 0 - OK here they are
1 0 - ONE
1 0 - TWO
1 1 - Missed some
1 0 - FIVE
0 0 - that's all

1 0 + I want to send some data
0 0 - OK send them
1 0 + FOO
1 1 - Nonono I don't want those after all
1 0 + BAR
0 1 + OK OK I'll stop

1 0 + Let's talk
1 0 - OK
1 0 + *voice data* …
1 0 - *also voice data* …
0 0 + hanging up
0 0 - duh
= = = ====

