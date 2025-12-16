# moat-lib-ring

% start synopsis

A simple opinionated character-based ring buffer.

This buffer, well, buffers. It's async compatible and can handle writes
overruns either by delaying the writer or by only keeping the newest data.

% end synopsis

Usage is very simple:

```python
from moat.lib.ring import RingBuffer

# Create buffer
ring = RingBuffer(200)

# write to it
nbytes = ring.write(b'Hello', drop=True)
assert nbytes == 5

# read from it
buf = bytearray(2)
assert ring.readinto(buf) == 2
assert buf == 'He'

```

## Overflow handling

If you write with `drop=True`, which is the default, writing to the buffer
will always succeed and return the length of the bytestring. On overflow,
the last bufsize-1 bytes will be preserved. The first byte you read will be
a null byte, to signal that data was lost.

`drop=False` means that writing will stall instead of destroying data: `write`
will return a smaller length than requested. The caller is responsible for
waiting until there is free space.


## Locking

This code doesn't know if it's called from a thread or not.
If required, please add your own.


## Async operation

`moat.lib.ring.aio` provides an async version.

Async writes always wait until all bytes have been
delivered to the buffer.


# Threaded operation

TODO. Requires a lock and thread-based events (or conditions).
