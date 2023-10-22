============
Hacking MoaT
============

+++++++++++++++++
Overall structure
+++++++++++++++++

MoaT programs consist of two (types of) parts: Apps and Streams.

An App does something, while a stream forwards data (app commands *or* raw
data) to and from someplace else.

On each MoaT system, its configuration file declares how the lcoal apps are
configured and connected, and how it connects to other systems.

----
Apps
----

Apps can be simple (no sub-apps) or more complex (arbitrarily many sub-apps).
A third type controls a single sub-app, transparently imbuing it with
features like automatic restart of errors or shielding the rest of the
system if it crashes.

Links to other systems are also apps. They convert calls to their
sub-hierarchy to messages and send them on, returning replies to the
caller. Thus an app doesn't have to care whether a peripheral it talks to
is local, or a system or three away.

Generic app base classes are named "…Cmd".

Structure
=========

MoaT's apps are connected to a named local hierarchy, much like a file
system with subdirectories.

MoaT's root app is `Dispatcher`. It interprets the top-level
configuration and starts named sub-apps. Calling commands of other apps
always starts there; MoaT does not have relative paths.

-------
Streams
-------

Stream types
============

MoaT streams come in three flavors, which build on top of each other.

Buf
+++

The lowest level is an unstructurd stream of bytes. Stream modules that
process those are named "…Buf". They provide `rd` and `wr` methods to read
and write arbitrary amounts of data.

Reading is always performed into a caller-provided buffer; the read command
returns the number of bytes filled. Reading does not wait for the buffer to
be full.

A write call returns when the whole buffer passed to `wr` has been transmitted.

Blk
+++

A structured stream of bytes, typically corresponding to one message oer
block (of some type). Stream modules that process byte blocks are named
"…Blk". They provide `snd` and `rcv` methods to read and write one block
each.

Reading returns a complete data block. It may be a memoryview; the caller
must not assume that the returned buffer will survive beyond the next call
to `rcv`.

Msg
+++

A (serializable) Python data structure, typically using a dict/map as the
top level. Stream modules that process structured data are named "…Msg".
They provide `send` and `recv` methods.


Combinations
++++++++++++

A "…MsgBuf" stream accepts messages and forwards them to a bytestream.
Examples are a MsgPack or CBOR codec, as these protocols are self-delimiting.

Likewise for "…MsgBlk" or "…BlkBuf".

On top of this, a "…CmdMsg" class accepts MoaT commands via its
``dispatch`` method and translates them to a standardizes mapping. See
`doc/messages.md`_ for details.

Out-of-band data
++++++++++++++++

Some streams support data that's not part of a message. This is of
particular importance when the communication to a satellite uses the same
connection as its `sys.stderr` stream.

MoaT's way to handle this is to prefix its messages with a signal byte.

The `crd` and `cwr` methods are used by "…BlkBuf" streams to process OOB
data. They work like `rd` and `wr` but bypass normal packaging. Typically,
"…Blk" and "…Msg" stream modules forward these calls to the next-lower
layer transparently.

Code structure
==============

Streams are async context managers. They connect when the context is
entered, and disconnect when it is exited. All configuration data is
extracted from the config file's structure.

The superclasses for basic streams implement a couple of basic helpers
to reduce your code's size.

stream
++++++

This async method sets up and returns the 
