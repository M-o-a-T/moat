###########
moat-modbus
###########

This is an anyio-enabled async frontend for pymodbus.

+++++
Usage
+++++

Check the example client and server for rudimentary usage.

Documentation patches gladly accepted.

++++++++++
Background
++++++++++

`moat-modbus` diverges from `pymodbus` in that it does not expose a "data
store" context to the user. Instead, every bus value is a separate object,
with arbitrary length and encapsulating its own encoding and decoding rules.

A Modbus server exposing writeable registers only needs to

* register the value in question

* wait for it to be written to

The rest happens behind the scenes.

+++++++++++++
Device Server
+++++++++++++

As some Modbus devices only allow ine server at a time, MoaT's Modbus
supports a simple bidirectional gateway.

How to get there:

* Write a generic device description. Put it in the modbus-data repository.

* Add an interface overlay that describes which topic to send the data to /
  which topic to read.

* Run ``moat modbus dev poll FILE.yaml``. You can use a generic systemd
  service if you copy the file to ``/etc/moat/modbus``.

The values can be modified (factor+offset); the gateway works in both
directions (command/state).

++++++++++++++++++++++++
MQTT / MoaT-KV interface
++++++++++++++++++++++++

MoaT-Modbus includes a server that's informed by a device profile. This server
acts as a bidirectional gateway from and to MQTT and/or MoaT-KV storage.

See "gateway.rst" for details.


TODO
++++

* configurable codecs
* get/set attributes
* pack multiple values into a message
* read-after-write if no slot
