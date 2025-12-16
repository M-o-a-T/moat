
# MoaT Link

% start synopsis
% start main

Moat-Link is a library that distributes messages between several possible
back-ends, channel arrangements or encodings.

The associated server links these backends into one coherent system,
provide message history, documentation, and whatnot.

% end synopsis

## Rationale

Often, services have differing ideas how to encode "their" messages.
For instance, Home Assistant likes JSON, except for boolean content which
is encoded as "ON" and "OFF". On the other hand, encodings like [msgpack] or
[CBOR] replace the overhead of textual analysis and repeated division by ten
with typed binary data.

MoaT-KV supported this usecase via its own MQTT server, which is based on
hbmqtt. Unfortunately hbmqtt is unsupported, high-overhead, and doesn't
support MQTT 5. MoaT-KV adds its own overhead and doesn't support
non-retained messages.

## Structure

MoaT-Link consists of a couple of related services.

### Server

The main server records messages in its history, affords redundancy,
can re-supply the MQTT server with retained state, and so on.

### Translator

Translators send and receive messages from other channels or topics.

For instance, Home Assistant's default of device state/cmd/control in one
single hierarchy doesn't always mesh well with other systems' ideas.

### Persistency, Redundancy

There can be multiple MoaT-Link servers. Clients automatically reconnect
when one of them disconnects or becomes unresponsive.

Planned: [support for multiple MQTT servers](todo-link-mqtt).


### Error handling

In a system that aspires to be reliable, misbehaving code needs to record
that it failed. MoaT-Link comes with a wrapper that auto-creates a problem
report, or deletes it when the problem no longer occurs.

TODO: basic infrastructure exists but reporting needs a heap of code
and there are a few parts that would benefit from error-handling
wrappers.

Of course, if the system that handles error reporting fails … there's
nobody to send an error. Thus, MoaT-Link also has a keepalive mechanism
that can automatically notify you as soon as one of the critical components
is down.

(This part works …)

### Data Schema

Any large system suffers from data rot. An extension to MoaT-Link (planned)
describes every message with a JSON schema and records mismatches.

### Web view

Last but not least, we want a HTML front-end for introspection and
debugging.

## Message Encoding

MoaT-Link supports various encodings, most notably CBOR and msgpack. Its
native default is CBOR because, unlike msgpack, CBOR's extensions are
simply normal (but tagged) data structures and thus are introspectable.

[aiomqtt]: https://github.com/sbtinstruments/aiomqtt
[cbor]: https://cbor.io/
[msgpack]: https://msgpack.org.

% end main
