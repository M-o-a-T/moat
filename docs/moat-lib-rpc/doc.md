# Built-in Documentation

MoaT supports (minimal) discovery. To that end, configuration for sub-apps
and parameters plus return values of commands are expected to be available
from the device in question.

Documentation is intentionally terse, as to not require more memory in
small(ish) satellites than absolutely necessary.

A sub-app's or command's documentation is stored in a dict. The following
keys are defined:

* ``_d``

  A short string that describes the command in question.

  The text does not contain a type.

* ``NAME``

  A named parameter / keyword argument.

* ``_a``

  Alternates. The value is an array with (at least two) mappings that
  update the base.


Classes use these additional keys:

* ``_c``

  This key describes the class / app itself. Only ``_d`` and named
  parameters are allowed.


Commands use these additional keys:

* ``_r``

  The return value. When streaming: the data sent in the terminal response.

* ``_k``

  Any keyword argument not explicitly mentioned.

  If this key is missing, no such keywords may be present.

* ``_NUM``

  A positional argument.

* ``_n``

  Trailing (or indeed any) positional arguments.

  If this key is missing, no additional positional arguments may be present.

  In data structures, the presence of this key (and the absence of any
  other keys except for ``_NUM`` and ``_d``) indicates that the
  element is a list, not a mapping.

  :::{note}
  If other keys are present, integer-values keys typically refer to an
  existing array.
  :::

* ``_m``

  If present, this field must contain an integer. It marks the first
  positional argument that may be omitted. If this key is absent, all
  given positional arguments are mandatory.


Commands that support streaming use these additional keys:

* ``_i``

  The incoming stream accepted by this command. If `True`, the documented
  interface is used as input.

* ``_o``

  The outgoing stream sent by this command. If `True`, the documented
  return value is used and the "real" result is empty.

* ``_s``

  This key is present if the command can be invoked with or without
  streaming. It may contain a list with two up to elements; the first applies to
  direct commands, the second to streaming. The contents are intended as
  updates to the parent dict (after considering ``_i`` and ``_o``, which
  should be in the top level, not in ``_s``).

  Alternately the value may be `True`, which means the same as an empty list.


* ``_R``

  The data sent in the initial response (i.e. the message from target to
  initiator that acknowledges the stream).

* ``_q``

  The data expected in the terminal command (i.e. the message from
  initiator to target that closes the stream).

One or both of ``_i`` and ``_o`` must be present.


If the value of any key (except ``_d`` and ``_m``) is a string, it should
be of the form ``type:purpose``. ``type`` is used as in Python's `typing`
module. ``purpose`` is a hopefully-human-readable text.

Otherwise the value can be a dict or a list, in which case the above
conventions are applied recursively. Use {py:obj}`Ellipsis` to specify
that the preceding description applies to all following elements.

Documentation for sub-apps describes its configuration keys; the only key
that starts with an underscore should be ``_d``.

If a (sub-)dict is optional, ``_x`` describes the options when the
value is not a dict.


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

The helper class `moat.lib.rpc.SubStore` can be used to
auto-reassemble the results of such a split:

    # standard
    res = await disp.app.cmd(…)

    # if the return type is "parts:"
    res = await SubStore(disp.app.cmd).get(…)


## Streamed paths

Streams that access a hierarchical structure frequently need to convey
which part of that structure they refer to.
