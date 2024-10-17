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

MoaT-KV supports this usecase via its own MQTT server, which is based on
hbmqtt. Unfortunately hbmqtt is unsupported, high-overhead, and doesn't
support MQTT 5. MoaT-KV adds its own overhead and doesn't support
non-retained messages.

Structure
+++++++++

The MoaT-Link client library supports multiple back-ends. It is designed to
use the most expedient channel. Thus, a client that is coded to Home
Assistant's view of the world can send its topics and messages to the MQTT
server for direct low-latency communication.

The MoaT-Link server will then read these messages and forward them to
all other channels with matching topic. It preserves MQTT's Retain flag,
QOS, and other metadata (if possible), and won't forward a message that's a
no-op.

Topics
++++++

MoaT-Link can support rearranging topics. For instance, Home Assistant's
default of device state/cmd/control in one single hierarchy doesn't always
mesh well with other systems' ideas.

Message Encoding
++++++++++++++++

MoaT-Link supports various encodings, most notably CBOR and msgpack. Its
native default is CBOR because, unlike msgpack, CBOR's extensions are
simply normal (but tagged) data structures and thus are introspectable.

