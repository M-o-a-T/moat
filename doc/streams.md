# Stream Handling

Python knows a lot of methods how to handle byte / object streams.
Unfortunately they're all somewhat incompatible.

## Existing interfaces

### asyncio

Byte streams use read/write.

asyncio's byte streams have a couple of annoying flaws: (a) separate send
and receive stream objects, (b) the infamous "write-then-drain" dance which
is inefficient and basically requires copying the buffer, (c) closing uses
a similar "close-then-wait" combination.

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

As per XKCD 927, MoaT uses a new scheme.

Byte and object streams use send/recv. Byte streams can use "recv\_to" as the
readinto equivalent.

The distinction between bytes and objects 

Streams have parent/child links. The parent is the next lower level. On the
top there's a "Request" object which serializes "send" requests, and a "StdBase"
that dispatches incoming commands to multiple subsystems.

Streams have a "run" method. The system sets up a stream stack and places
subsystems on top of it as per the configuration data. Then it starts
the stack's bottom "run", which sets up itself and then runs the next "run"
up. `StdBase.run` then starts the subsystems.

