# MoaT Message Structure

Links between MoaT devices are always one-to-one and bidirectional.
There is no master/slave relationship.

MoaT uses a multi-level encapsulation strategy. The elements in this
list are applied in sequence. Any element might be missing.

## MoaT-Lib-CMD

MoaT messaging uses the ``moat.lib.cmd`` library for bidirectional RPC,
streaming, and error reporting.

## Reliability

If message loss or reordering is possible, a
:moat.micro.proto.reliable:`ReliableMsg` wrapper is used.

## Serialization

Messages are typically serialized with the ``StdCBOR`` codec.

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


# Documentation

MoaT supports (minimal) discovery. To that end, configuration for sub-apps
and parameters plus return values of commands are expected to be available
from the device in question.

Documentation is intentionally terse, as to not require more memory in
small(ish) satellites than absolutely necessary.

A sub-app's or command's documentation is stored in a dict. The following
keys are defined:

* ``_d``

  A short string that describes the object or command in question.

  The text does not contain a type.

* ``NAME``

  A named parameter / keyword argument.


Commands use these additional keys:

* ``_r``

  The return value. When streaming, the data sent in the terminal response.

* ``_k``

  Any keyword argument not explicitly mentioned.

  If this key is missing, no such keywords may be present.

* ``_NUM``

  A positional argument.

* ``_a`

  Trailing positional arguments.

  If this key is missing, no additional positional arguments may be present.

* ``_m``

  If present, this field must contain an integer. It marks the first
  positional argument that may be omitted. If this key is absent, all
  given positional arguments are mandatory.


Commands that support streaming use these additional keys:

* ``_i``

  The incoming stream accepted by this command.

* ``_o``

  The outgoing stream sent by this command.

* ``_s``

  This key is present if the command can be invoked with or without
  streaming. It contains a list with two elements; the first applies to
  direct commands, the second when streaming. The contents are intended as
  possibly-recursive updates to the parent dict.

  This value may contain a dict, in which case it applies to the streaming
  case, i.e. it is equivalent to a list with an empty first element.

* ``_R``

  The data sent in the initial response.

* ``_q``

  The data expected in the terminal command.

One or both of ``_i`` and ``_o`` must be present. String values of ``_i``
and ``_o`` shall be interpreted as if they were values of a nested ``_0``
key.


If the value of any key (except ``_d`` and ``_m``) is a string, it should
be of the form ``type:purpose``. ``type`` is used as in Python's `typing`
module. ``purpose`` is a hopefully-human-readable text.

Otherwise the value can be a dict, in which case the above conventions are
applied recursively. (Obviously such a sub-dict may not contain ``_r``,
``_s``, _i`` or ``_o``.)

Documentation for sub-apps describes its configuration keys; the only key
that starts with an underscore should be ``_d``.


## Partial replies

A result of type ``parts`` indicates that the result may be too big to
comfortably fit in the small message frames typically used by MoaT
satellites.

In this case the result may be transmitted partially, as a two-element
list. The first element is a dict or list that contains the "short" members
of the return value, i.e. those that serialize to just a couple of bytes.
The second element is a list of keys or offsets that tell the recipient
which missing entries it should fetch in separate calls.

By convention, the parameter ``p`` contains the path to the sub-reply that
this call accesses. It must default to ``()`` and is not documented
explicitly.


### Example

Consider this documentation entry to a hypothetical logger:

    _d: Mangle, crumble, and/or log messages.
    _0: str:log message
    _1: int:level
    _2: float:Timestamp
    _m: 1
    _r:
      _d: saved position
      _0: int:file offset
      _1: int:sequence#

The reply to a ``doc_`` request might look like this:

    - _0: str:log message
      _1: int:level
      _2: float:Timestamp
      _m: 1
    - - _r
      - _d

To reassemble this, the client needs to send two other requests:

    xxx.doc_ (p=P("_d"))

which returns

    "Mangle, crumble, and/or log messages."

and

    xxx.doc_ (p=P("_r"))

resulting in

    _d: saved position
    _0: int:file offset
    _1: int:sequence#

Both are used as-is since they are not two-element lists. If they were, the
process would recurse.

The helper class :moat.micro.cmd.tree.dir:`SubStore` can be used to
auto-reassemble the results of such a split:

    # standard
    res = await disp.app.cmd(…)

    # if the return type is "parts:"
    res = await SubStore(disp.app.cmd).get(…)


## Streamed paths

Streams that access a hierarchical structure frequently need to convey
which part of that structure they refer to.
