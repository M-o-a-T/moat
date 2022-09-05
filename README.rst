###########
asyncmodbus
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

`asyncmodbus` diverges from `pymodbus` in that it does not expose a data
store, context to the user. Instead, every bus value is a separate object,
with arbitrary length and encapsulating its encoding and decoding rules.

A Modbus server exposing writeable registers only needs to

* register the value in question

* wait for it to be written to

The rest happens behind the scenes.

