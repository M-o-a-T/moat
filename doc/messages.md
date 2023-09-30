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

* d

  Data. Requests contain a dict: keyword args to the command in question.
  Replies contain whatever the called command returns.


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

A request for iterated results adds an integer parameter `r`.
The initial reply also contains this key, possibly modified. If `r` is
returned as `False` the iterator is empty. Iterator replies don't have `a`
or `d` elements.

Values will then be sent as normal replies, in both directions.

The originator may send additional messages at will; the recipient will get
polled as per the Python iteration protocol and is thus rate limited.

The stream is terminated by a message with `r` set to `False`, an
exception, or a cancellation.


