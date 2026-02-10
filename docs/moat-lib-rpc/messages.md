(moat-lib-rpc-messages)=
# MoaT Messaging

Links between MoaT devices are one-to-one and bidirectional.
There is no master/slave relationship.

MoaT uses a multi-level encapsulation strategy.

## RPC

MoaT messaging uses this library for bidirectional RPC,
streaming, and error reporting.

## Reliability

If message loss or reordering is possible, a
:moat.micro.proto.reliable:`ReliableMsg` wrapper is used.

## Serialization

Messages are typically serialized with the ``moat-cbor`` codec.

TODO: The codec might create object proxies.
These should be deleted when no longer in use.

## Delimiting

If the stream might contain non-message traffic (typically: when the packet
stream is multiplexed onto the serial console), a leading character is
inserted in front of every message. Obviously the lead character should be
chosen as not to occur in the console data stream. Ideally it should not
occur often in the serialized messages, but this is not a requirement.

## Framing

To reject altered messages, a `SerialPacker` is used.

MoaT sends and expects exactly one message per frame.

# Command structure

MoaT commands are somewhat hierarchical. While there is no global root,
links to remote devices look just like sub-devices and are used as such.


## Special commands

### doc\_

Retrieve an app's or a command's description.

This command is appended. If a handler is addresses by ``r.fs.open``, its
documentation should be available at ``r.fs.open.doc_``.

Documentation contents are described below.

### cfg\_

Retrieve the configuration data of an object.

### dir\_

Retrieve an app's directory, i.e. a list of commands and sub-apps.

Directory entries that end with a trailing underscore are skipped unless
``v=True``.

The result is a dict with these keys:

* c

  A list of available direct commands.

* s

  A list of available streamed commands.

* d

  A dict of sub-apps. The value is the Python class of the app.

* C

  A flag; if set, the target can be called directly.

* S

  A flag; if set, the target can be called as a stream.



### upd\_

Reload this object. A subtree reloads all subcommands.

### rdy\_

Check whether this object is ready.

If `w` is `True` (the default), don't return until it is.

Return value:

* `False`: ready, no wait necessary.

* `True`: down.

* `None`: going up, or (when `w` is set) signalling that the caller
  did have to wait for readiness.

This command is not available if the satellite runs in "small" mode.

### stp\_

Stop this subsystem.

The command returns when the subsystem is halted.

### stq\_

Query stop state.

XXX do we need this?

### doc\_

Documentation of this message / object.

See {doc}`Built-in Documentation <doc>` for details.
