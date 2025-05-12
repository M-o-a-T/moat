# Stream Handling

Python knows a lot of methods how to handle byte / object streams.
Unfortunately they're all somewhat incompatible.

## Existing interfaces

### asyncio

Byte streams use read/write.

asyncio's byte streams have a couple of annoying flaws: (a) separate send
and receive stream objects, (b) the infamous "write-then-drain" dance,
which is inefficient and basically requires copying the buffer, (c) closing
uses a similar "close-then-wait" combination.

There are no object streams. Queues use get/put.

### MicroPython Core

#### sync

Byte streams can use recv/send, but also support read (all until given
limit or EOF), and write/sendall.

MicroPython adds a "readinto" method that reads into an existing buffer, to
save on memory re-allocations.

#### async

MicroPython's asyncio drops the separate read+write streams but otherwise
inherits asyncio's interface. It also implements "readinto".

### anyio

AnyIO distinguishes between byte and object streams. Both use send/receive.
Buffered byte streams also have receive\_exactly and receive\_until.

### trio

Object streams (channels) use send / receive, byte streams
send\_all / receive\_some.


## MoaT

As per XKCD 927, MoaT uses a new naming scheme.

Byte streams use rd/wr. Object streams use send/recv.

`rd` is equivalent to `readinto`.

### Type hierarchy

All MoaT streams are running as context managers. This
simplifies the code structure and allows for clean restarting.

As a consequence, non-abstract types need to overide at least the ``_ctx`` method.

#### BaseMsg / BaseBuf

Subclasses of these implement translation of object or byte streams to whatever
lower layer that's not part of the MoaT stream system.

You need to override rd/wr (BaseBuf) or send/recv (BaseMsg), and the
context handler "\_ctx".

Defined in ``moat.micro.proto.stack``.

##### FileBuf

Base implementation for translation of MoaT to a "normal" MicroPython file
object, socket, or whatever. 

(On CPython, MoaT does not use sync streams.)

Your context handler needs to create the stream and assign it to ``s``.

Defined in ``moat.micro.proto.stream``.

##### AIOBuf

Base implementation for translation of MoaT to MicroPython's asyncio streams.

On CPython, MoaT uses anyio's streams. See ``AnyioBuf``.

Your context handler needs to open the stream and assign it to ``s``.

Defined in ``moat.micro.proto.stream``.

##### AnyioBuf

Base implementation for translation of MoaT to AnyIO's streams, including
files (via `anyio.Path`).

Your context handler needs to open the stream and assign it to ``s``.

Defined in ``moat.micro.proto.stream``.


##### ProcessBuf

A stream that connects to stdin+stdout an external process.

Defined in ``moat.micro.proto.stream``.


#### StackedMsg / StackedBuf

Subclasses of these implement translation of object or byte streams to whatever
lower layer that are part of the MoaT stream system. Examples are logging
or message loss recovery.

Streams have a parent links. The parent is the next lower level.

The default implementation simply forwards everything to the parent.

Defined in ``moat.micro.proto.stack``.

##### Naming convention

* \*Msg

  message objects (send/recv)

* \*Blk

  accepts segments of bytes, corresponding to one message each (snd/rcv)

* \*Buf

  accepts unstructured streams of bytes (rd/wr)


Class names end with one or two of these three-letter sequences. The second
part of the name denotes which type is sent on, if the module converts from
one to the other.


### Stream helper objects

#### UnixLink

A BaseBuf that connects to a named socket.

Defined in ``moat.micro.net.unix``.


#### NetLink

A BaseBuf that connects to a TCP socket.

Defined in ``moat.micro.net.net``.


#### ProcessLink

A BaseBuf that connects to stdin/stdout of a process.

Defined in ``moat.micro.net.process``.


#### ReliableMsg

A stacked object that retransmits lost messages.


#### ReconnectBuf

A stacked object that mostly-transparently reconnects broken links.

A ReconnectBuf doesn't prevent message loss. Use a `ReliableMsg` above it.

TODO.


#### MsgpackMsgBuf

A stream translator that encapsulates structured messages to a MsgPack bytestream.

Console messages are passed through transparently.

Defined in ``moat.micro.proto.stream``.


#### MsgpackMsgBlk

Like MsgpackMsgBuf, except that encoded messages are sent and expected in
message-sized chunks of bytes.


#### SerialPackerBlock

A stream translator that encapsulates chunks of bytes in SerialPacker data.


#### SingleAIOBuf, SingleAnyioBuf

Single-use wrappers for `AIOBuf` and `AnyioBuf`, respectively.

Useful mainly in network protocol handlers.


#### Linux specific

None, currently.


# Command handling

.. TODO maybe move this

MoaT command handlers are arranged in a hierarchy, accessed by paths from
the root – similar to directories and files, except that MoaT doesn't use a
slash as path separator.

Paths are either lists of path elements or simple strings. Using the
latter, all but the last element is interpreted as a one-letter index to
the next level.

The hierarchy is per device. Links to other devices are simply command
handlers that forward the rest of the path to the root of the remote
system.

TODO: implement a tracing feature so that commands can track their return
path.


## Link Commands

.. TODO move this

This section describes commands for sending and receiving raw or packetized
data (``wr``/``rd``), console data that are sent outside of packaging
(``cwr``/``crd``), or message frames (``w``/``r``). They work on all of
MoaT's communication channels, though the exact semantics depend on the
link configuration of the app that controls the port. (You won't get
structured data on a raw serial port, or vice versa.)

w
--

Send a packet with structured data (``m``).

wr
--

Transmit bytes (``b``).

cwr
---

Transmit raw (console) data (``b``)

r
--

Read a message.

rd
--

Read up to ``n`` raw bytes (default 64).

crd
---

Read up to ``n`` console bytes (default 64).

