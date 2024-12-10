The Fake Bus
============

This code connects to a "fake" wired-OR bus.

The bus itself is provided by a demon (``python/fakebus/bus.py``) that simply
reads a byte from all connected sockets, ORs them, and sends the result
back. Repeat whenever some device sends an update that actually changes the
bus state.

NB: in principle you can do the same thing with RIOT's ``gpio_socket``
module. While that works, it's too computationally expensive for regression
tests that check bus stability.

Modules
+++++++

bus
---

The actual fakebus client code.

Support programs
++++++++++++++++

msgio
-----

A bus monitor program. Can also be used to send messages.

serial
------

A program that bidirectionally translates MoaT messages from serial format
(on stdin/stdout) from/to states on the Fakebus.

spam
----

A very simple hack that introduces random bus signals.

