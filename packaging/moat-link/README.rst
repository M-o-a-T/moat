+++++++++
MoaT Link
+++++++++

Moat-Link is a library that distributes messages between several possible
back-ends, channel arrangements or encodings.

The associated server links these backends into one coherent system,
provide message history, documentation, and whatnot.

Rationale
+++++++++

Often, services have differing ideas how to encode "their" messages.
For instance, Home Assistant likes JSON, except for boolean content which
is encoded as "ON" and "OFF". On the other hand, encodings like msgpack_ or
CBOR_ replace the overhead of textual analysis and repeated division by ten
with typed binary data.


.. _aiomqtt: https://github.com/sbtinstruments/aiomqtt
.. _CBOR: https://cbor.io/
.. _msgpack: https://msgpack.org.

MoaT-KV supported this usecase via its own MQTT server, which is based on
hbmqtt. Unfortunately hbmqtt is unsupported, high-overhead, and doesn't
support MQTT 5. MoaT-KV adds its own overhead and doesn't support
non-retained messages.

Structure
+++++++++

MoaT-Link consists of a couple of related services.

Server
------

The main server records messages in its history, affords redundancy,
can re-supply the MQTT server with retained state, and so on.

Translator
----------

Translators send and receive messages from other channels or topics.

For instance, Home Assistant's default of device state/cmd/control in one
single hierarchy doesn't always mesh well with other systems' ideas.

Errors
------

MoaT-Link supports error handling and recovery.

Web view
--------

Last but not least, we want a HTML front-end for introspection and
debugging.


Message Encoding
++++++++++++++++

MoaT-Link supports various encodings, most notably CBOR and msgpack. Its
native default is CBOR because, unlike msgpack, CBOR's extensions are
simply normal (but tagged) data structures and thus are introspectable.

