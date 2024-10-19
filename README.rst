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
basic async methods too iterate on messages to send, and to feed incoming
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
        
    async with Transport() as tr, anyio.create_task_group() as tg:
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

        def handler():
            # process incoming commands
            while True:
                msg = await tr.cmd_in()
                try:
                    res = await handle_command(msg)
                except Exception as exc:
                    await msg.send_error(exc)
                else:
                    await msg.send()

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

All messages are arrays with at least two members. Non-array messages
MAY be used for out-of-band communication.

A transport that enforces message boundaries MAY send each message without
the leading array mark byte(s). In this case, all single-element messages
MUST be considered out-of-band.

All message exchanges start with a Command message and ends with a Reply.
If the Streaming bit is set, further messages will follow. The first
message with the Streaming bit set is not considered to be part of the
stream; neither is the terminal message with that bit clear.

There is no provision for messages that are not replied to. We recommend to
use out-of-band messages in this case.

Message format
++++++++++++++

A Moat-Cmd message consist of one preferably-small signed integer, plus a
variable but non-empty amount of data.

The leading integer is interpreted as follows.

* Bit 0: if set, the message starts or continues a data stream; if clear,
  it either ends a stream or consititues a standalone reply.

* Bit 1: Error/Warning.

All other bits contain the message ID, left-shifted by two. This scheme allows
for five concurrent messages per direction before encoding to two bytes
is required.

Negative integers signal that the ID has been allocated by that message's
recipient. They are inverted bit-wise, i.e. ``(-1-id)``. Thus an ID of zero
is legal. The bits described above refer to the ID's non-negative value.


ID allocation
-------------

Message IDs are assigned by the requestor. The ID spaces of both sides are
independent; the message type specifies which ID space is used.

IDs MUST NOT be reused if a stream using this ID is active in either direction.


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
1 1 - NB: Oops I think I missed some here
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

