# The MoaT-Command library

% start main

## Rationale

% start synopsis

This library is a generalization of the Remote Procedure Call pattern.
Aside from the basics (call a method, get a reply back asynchronously)
it supports cancellation (both client- and server-side), exception
forwarding, and streaming data (bidirectionally).

% end synopsis

## Prerequisites

For RPC, MoaT-Lib-Cmd requires a reliable underlying transport for Python
objects. MoaT uses CBOR; however, any reliable, non-reordering messsage
stream that can encode basic Python data structures (plus whatever
objects you send/receive) works.

MoaT-Lib-Cmd does not itself call the transport. Instead, it contains basic
async methods to iterate on messages to send, and to feed incoming
lower-level data in.

Local use, i.e. within a single process, does not require a codec.

## Usage

### No transport

``` python
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
```

### Using a transport

TODO

## API Specification

TODO

## Transport Specification

MoaT-Lib-Cmd messaging is simple by design. A basic interaction starts with
a command (sent from A to B, Streaming bit off) and ends with a reply (sent
from B to A, Streaming bit off).

There is no provision for messages that don't have a reply. However,
an "empty" reply is just three bytes and the sender is not required
to wait for it.

The side opening a sub-channel uses a unique non-negative integer as
channel ID. Replies carry the ID's bitwise-negated value. Thus the ID
spaces of both directions are inherently separate.

IDs are allocated when sending the first message on a sub-channel. They
MUST NOT be reused until final messages (stream bit off) have been
exchanged in both directions. Corollary: Exactly one final message MUST
be sent in both directions.

### Message format

A Moat-Cmd message consist of a preferably-small signed integer, plus a
variable and usually non-empty amount of data.

The integer is interpreted as follows.

- Sign: message direction.
- Bit 0: if set, the message starts or continues a data stream; if
  clear, the message is the final message for this subchannel and
  direction.
- Bit 1: Error/Warning. If bit 0 is clear, the message denotes an error
  which terminates the channel. Otherwise it is a warning or similar
  information, and SHOULD be attached to the following command or reply.

:::{tip}
If a transport is more efficient when encoding small positive numbers
(e.g. [MesssagePack](https://github.com/msgpack/msgpack/blob/master/spec.md)),
the integer shall be shifted one bit to the right instead of being
inverted. The direction is then encoded in the bit 0 (1: ID was negative).
:::

The other bits contain the message ID. Using CBOR (MessagePack), this
scheme allows for five (four) concurrent messages per direction before
encoding to two bytes is required.

Negative integers signal that the ID has been allocated by that
message's recipient. They are inverted bit-wise, i.e. `(-1-id)`. An
ID of zero is legal. The bits described above are not affected by this
inversion. Thus a command with ID=1 (no streaming, no error) is sent
with an initial integer of 4; the reply would use -5.

An interaction has concluded when both sides have transmitted exactly one
message with the Streaming bit clear.

### Streaming

An originator starts a stream by sending an initial message with the
Streaming bit set.

Data streams are inherently bidirectional. The command's semantics
should specify which side is supposed to send data (originator,
responer, or both). Error -2 will be sent (once) if a streamed item is
received that won't be handled.

Streaming may start when both sides have exchanged initial messages, i.e.
the originator may not send streamed data before receiving the initial
reply (with the Stream bit set).

The initial and final message are assumed to be out-of-band data. This also
applies to warnings.

#### Out-of-band data

Messages with both streaming and error bits set may be used to carry
out-of-band data while the stream is open, e.g. advising the recipient of
data loss. Conceptally, these messages are attached to the command or reply
that immediately follows them.

Application-generated warnings may not contain of single integers because
they conflict with the flow control mechanism (see next section).
The API should use payload formatting rules to avoid this situation
transparently.

#### Flow Control

For the most part: None. MoaT-Cmd is mostly used for monitoring events
or enumerating small data sets.

However, *if* a stream's recipient has limited buffer space and sends a
command that might trigger a nontrivial amount of messages, it may send
a specific warning (i.e. a message with both Error and Streaming bits
set) before its initial command or reply. This warning must consist of a
single non-negative integer that advises the sender of the number of
streamed messages it may transmit without acknowledgement.

During stream transmission, the recipient periodically sends some more
(positive) integers to signal the availability of more buffer space. It
must send such a message if the counter is zero (after buffer space becomes
available of course) and more messages are expected.

The initial flow control messages should be sent before the initial
command or reply, but may be deferred until later.

A receiver should start flow control sufficiently early, but that isn't
always feasible. It notifies the remote side (error/warning -5, below) if
an incoming message was dropped due to resource exhaustion; likewise, the
API is required to notify the sender.

## Payload conventions

The contents of messages beyond the initial integer is up to the
application. However, the following conventions are used by the rest of
MoaT:

- Initial messages start with the message's destination at the receiver,
  interpreted as a Path.

- Messages consist of a possibly-empty list of positional arguments /
  results, followed by a mapping of keyword+value arguments or results.

- The trailing mapping may be omitted if it is empty and the last positional
  argument is not a mapping. This also applies when there are no positional
  arguments.

- An empty mapping must not be omitted when the message is a warning
  and consists of a single integer.


## Error handling

The exact semantics of error messages are application specific.

Error messages with the streaming bit clear terminate the command. They
should be treated as fatal.

Error messages with the streaming bit set are either flow control
messages (see above) or out-of-band information from one endpoint
to the other.

% end main

### Well-Known Errors

- -1: Unspecified

  The `.stop()` API method was called.

  This message MAY be sent as a warning.

  Usage: assume that a sender reads and transmits a sequence of ten
  measurements each second. If a "stop" warning arrives, the sender
  should complete the current block before terminating, while a "stop"
  error forces the current transmission to end immediately.

- -2: Can't receive this stream

  Sent if a command isn't prepared to receive a streamed request or
  reply on this endpoint.

- -3: Cancel

  The sender's or receiver's task is cancelled: the work is no longer
  required / performed.

  This message should not be transmitted as a warning; that would be
  pointless.

- -4: No Commands

  The sender of this error doesn't process commands.

- -5: Data loss

  An incoming message was dropped due to resource exhaustion (full
  queue).

  This message should be sent as a warning.

- -6: Must stream

  Sent if a command will not handle a non-streamed request or reply.

- -7: Error

  Used if the "real" error could not be encoded for some (equaly
  untransmittable) reason. Typically includes a text dump of the
  problematic exception.

- -11 …: No Command

  The command is not recognized.

  The error number encodes the command's position for a hierarchical
  lookup at the destination, i.e. if the command is ("foo","bahr","baz")
  and "foo" doesn't know about "bahr", the error is -12.

  TODO

Other errors are sent using MoaT's link object encapsulation, i.e. the
error type (either a proxy or the name of the exception) followed by its
argument list and keywords (if present).

### Examples

> [!NOTE]
> Legend: \* S: Streaming \* E: Error \* D: direction / sign of message
> ID

Simple command:

| S   | E   | D   | Data    |
|-----|-----|-----|---------|
| \-  | \-  | \+  | Hello   |
| \-  | \-  | \-  | You too |

Simple command, error reply:

| S   | E   | D   | Data                       |
|-----|-----|-----|----------------------------|
| \-  | \-  | \+  | Hello again                |
| \-  | \*  | \-  | Meh. you already said that |

Receive a data stream:

| S   | E   | D   | Data              |
|-----|-----|-----|-------------------|
| \*  | \-  | \+  | gimme some data   |
| \*  | \-  | \-  | OK here they are  |
| \*  | \-  | \-  | ONE               |
| \*  | \-  | \-  | TWO               |
| \*  | \*  | \-  | Missed some       |
| \*  | \-  | \-  | FIVE              |
| \-  | \-  | \+  | \[ 'OopsError' \] |
| \*  | \-  | \-  | SIX               |
| \-  | \-  | \-  | stopped           |

Transmit a data stream:

| S   | E   | D   | Data                                |
|-----|-----|-----|-------------------------------------|
| \*  | \-  | \+  | I want to send some data            |
| \*  | \-  | \-  | OK send them                        |
| \*  | \-  | \+  | FOO                                 |
| \-  | \-  | \-  | Nonono I don't want those after all |
| \*  | \-  | \+  | BAR                                 |
| \-  | \*  | \+  | OK OK I'll stop                     |

Receive with an error:

| S   | E   | D   | Data                                                               |
|-----|-----|-----|--------------------------------------------------------------------|
| \*  | \-  | \+  | gimme some more data                                               |
| \*  | \-  | \-  | OK here they are                                                   |
| \*  | \-  | \-  | NINE                                                               |
| \*  | \-  | \-  | TEN                                                                |
| \-  | \*  | \-  | \[ 'CrashedError', -42, 'Owch', {'mitigating': 'circumstances'} \] |
| \-  | \-  | \+  | *sigh*                                                             |

Bidirectional data stream:

| S   | E   | D   | Data               |
|-----|-----|-----|--------------------|
| \*  | \-  | \+  | Let's talk         |
| \*  | \-  | \-  | OK                 |
| \*  | \-  | \+  | *chat data* …      |
| \*  | \-  | \-  | *more chat data* … |
| \-  | \-  | \+  | hanging up         |
| \-  | \-  | \-  | oh well            |

Data stream with flow control:

<table>
<thead>
<tr class="header">
<th>S</th>
<th>E</th>
<th>D</th>
<th>Data</th>
</tr>
</thead>
<tbody>
<tr class="odd">
<td>*</td>
<td>*</td>
<td>+</td>
<td>2</td>
</tr>
<tr class="even">
<td>*</td>
<td>-</td>
<td>+</td>
<td>gimme your data</td>
</tr>
<tr class="odd">
<td>*</td>
<td>-</td>
<td>-</td>
<td>OK here they are</td>
</tr>
<tr class="even">
<td>*</td>
<td>-</td>
<td>-</td>
<td>A</td>
</tr>
<tr class="odd">
<td>*</td>
<td>*</td>
<td>+</td>
<td>1</td>
</tr>
<tr class="even">
<td>*</td>
<td>-</td>
<td>-</td>
<td>BB</td>
</tr>
<tr class="odd">
<td>*</td>
<td>*</td>
<td>+</td>
<td>1</td>
</tr>
<tr class="even">
<td>*</td>
<td>-</td>
<td>-</td>
<td>CCC</td>
</tr>
<tr class="odd">
<td><ul>
<li></li>
</ul></td>
<td><ul>
<li></li>
</ul></td>
<td><ul>
<li></li>
</ul></td>
<td><p>DDDD [ time passes until the originator has free buffer(s)
]</p></td>
</tr>
<tr class="even">
<td>*</td>
<td>*</td>
<td>+</td>
<td>5</td>
</tr>
<tr class="odd">
<td>*</td>
<td>-</td>
<td>-</td>
<td>EEEEE</td>
</tr>
<tr class="even">
<td>*</td>
<td>-</td>
<td>-</td>
<td>FFFFFF</td>
</tr>
<tr class="odd">
<td>*</td>
<td>-</td>
<td>-</td>
<td>GGGGGGG</td>
</tr>
<tr class="even">
<td>-</td>
<td>-</td>
<td>-</td>
<td>that's all</td>
</tr>
<tr class="odd">
<td>-</td>
<td>-</td>
<td>+</td>
<td>thx</td>
</tr>
</tbody>
</table>
