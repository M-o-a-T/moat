# MoaT Serial Message Structure

Messages are encoded using CBOR/MsgPack maps. Short keywords are used to
conserve client memory.

## Simple messages

* a

  Command Action. May be either a string or a list of strings / integers.

  If this field is missing, the message is a reply (`d` present) or a
  cancellation (`d` also missing).

  Integer items are used to refer to a list of sub-items, e.g. one of 20
  thermometers or individual connections of a listening socket.

  The first character of an action may be ``!``, indicating that the action
  should be applied locally instead of getting forwarded.

  If the first character of an action is ``?``, the command won't wait for
  the app to be "ready". This is dangerous if applied to any command other
  than ``rdy``.

* d

  Data. Requests contain a dict: keyword args to the command in question.
  Replies contain whatever the called command returns.

* x

  List of expected exception types. Commands only.

  If the recipient encounters one of these, it will still send it back to
  the sender but it won't log them. Use case is e.g. file system errors
  where "file not found" is not the client's fault, or config updates where
  a missing key will simply be sent.

## Request/Reply

* i

  Sequence number. An action with a sequence number *must* be replied to,
  eventually. Actions without sequence numbers are unsolicited typed status
  messages. Replies without sequence numbers don't make sense.

  A sequence number generator sets the low bit. On receipt this bit is
  inverted, thus the sequence number spaces of both sides are kept
  separate.

* e

  Error, in replies. The content is either a string or a well-known proxy
  for the error's type.

  The data element of errors must be a list (arguments to the error's
  constructor).


## Cancellations

A message with only an `i` element cancels the operation.

## Iteration

Repeated values, e.g. measurements or remote serial data, should not
require sending "pull" requests every however-many milliseconds, esp. when
they end up being larger than the reply.

Thus the MoaT protocol offers a method to set up bidirectional message streams.

* r

  Interval between reply messages, in milliseconds. Must be greater than zero, or `False`.

* n

  Counter for iterated messages. A store-and-forward transport (e.g.
  `Reliable`) uses this sequencer and `i` to update the buffered message
  instead of storing an unbound amount of stale data that are useless by
  the time the iterator's recipient gets them.


A request for iterated results adds an integer parameter `r`.
The initial reply also contains this key, possibly modified. If `r` is
returned as `False` the iterator is empty. Iterator replies don't have `a`
or `d` elements.

Values will then be sent as normal replies, in both directions.

The originator may send additional messages at will; the recipient will get
polled as per the Python iteration protocol and is thus rate limited.

The stream is terminated by a message with `r` set to `False`, an
exception, or a cancellation.


## Common commands

### dir\_

Retrieve an app's directory, i.e. a list of commands and sub-apps.

Docstrings are not supported.

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

