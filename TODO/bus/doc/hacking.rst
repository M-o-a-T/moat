====================
Hacking the MoaT bus
====================

++++++++++++++
Code structure
++++++++++++++

References to code that do not have an extension apply to Python (``.py``)
C (``.c``/``.h``), and Forth (``.fs``) implementations. Care must be taken
to keep those interoperable, though usage details necesarily differ.

----------------------
Physical bus interface
----------------------

``moat.bus.handler`` implements sending and receiving buffered bus messages.
Both use an I/O-less strategy so that they can be used however necessary.

There currently is no implementation of a buffer-less sender or receiver.
Feel free to add one.

Encapsulation of bus messages is handled by ``moat.bus.message``.

--------------------
Serial bus interface
--------------------

The serial adapter is in ``c/serial.c``; the Python version is in
``moat.bus.serial``. Both are based on ``SerialPacker``.

-------------------------
Microcontroller interface
-------------------------

TODO

--------
C macros
--------

* MOAT_USE_REF

  Define this if you have more than one bus and thus your code needs a
  callback.

* MOAT_WIRES

  Use the n-wire interface. Define as the number of wires. Between 2 and 4 inclusive.

* MOAT_WIRE_1

  Port of the first wire.

* MOAT_WIRE_2

  Port of the second wire. [and so on]

* MOAT_DEBUG_WIRES

  Emit a serial notification whenever the wire state changes.

  Possibly slow!

* MOAT_SERIAL

  Use the serial packet interface.

* MOAT_REPEATER

  Transfer all messages received on A to B and vice versa. Define as the
  (positive) server address SA (1..3).

  A Bus ACK is sent if an message is addressed to -SA or -4 (server broadcast).
  Otherwise this is transparent, i.e. *all* messages are forwarded.

* MOAT_GATEWAY

  Transfer messages received on A to B and vice versa.

  This implements an addressed gateway.

  Not yet implemented.

* DEBUG_ADDR

  If set, use its value as a minifloat delay for address requests.
  Otherwise uses a random value based on cpu serial and timer.

++++++++++
Simulation
++++++++++

Debugging on embedded systems is difficult; you can't attach a debugger
because that disrupts bus timing.

Thus MoaT provides you with a variety of tools to simulate a MoaT bus in
software, hopefully enabling you to do the necessary debugging on the host.

------------------------
Low-level bus simulation
------------------------

The state of the bus wires is encoded to a byte; that byte is sent to a
daemon on a Unix socket which reads it, ORs it to the latest bytes from
all other clients, and then sends the updated bus state to them, applying a
variable delay to simulate bus latency.

This bus is implemented by ``moat.bus.fake.bus``.

``fakebus/send`` and ``fakebus/recv`` send one message and receive any
number of messages, respectively. The common code for bus access is in
``fakebus/client``.

``c/fake/bus/spam.c`` transmits random changes to the bus.

Finally, ``c/fake/bus/serial.c`` treats its stdin/stdout like a serial wire
and bidirectionally forwards messages from that to the fakebus and back.

Like on the real bus, debugging disrupts the low-level bus simulator.

For a full-stack simulation, "moat.bus.fake.server.py" starts the serial
adapter and then attaches the bus master module to it.

-------------------------
High-level bus simulation
-------------------------

We use MQTT. The message's bytes (without header) are sent to the
test/raw/moatbus/SRC/DST/CODE topic.


+++++++++++++++++++
Hardware Test setup
+++++++++++++++++++

Simulating a bus is nice but at some point we need to use actual
hardware.

Our standard test setup requires a Raspberry Pi 2 (or better). You need
three Blue Pill boards, three **3.3V TTL** serial bus adapters (two if you
use the Pi's built-in serial; remember to turn off the console and
Bluetooth serial ports), four 10k resistors (for bus pull-up) and two
standard-sized breadboards if you don't want to have the Pills float around
your desk.

If you don't have a Pi: anything that runs Linux and can handle three TTL
serial ports and twelve 3.3V digital ports will work. You'll need to
translate GPIO pin numbers, of course.

Install ``stm32flash``. If you want to debug on the Pill with gdb, also
install ``openocd`` (from Bullseye or better; the version from Buster
doesn't work).


-----------
Connections
-----------

Let's name the Blue Pill boards A, B and C. Their serial ports should be
/dev/pill_a through /dev/pill_c; one way to create them is with something
like the udev rules in ``ci/71-serial.rules``. You'll need to change the
serial numbers and USB product IDs to match yours.

Pins ``SIO``, ``CLK`` and ``BT0`` are *not* located on the Pill's
breadboard headers. ``SIO`` and ``CLK`` are the second and third pins on
the 4-pin serial debug header (opposite the USB port). They may also be
described as ``O`` and ``LK`` or ``DIO`` and ``CLCK`` or ``SWDIO`` and
``SWCLK``.

``Boot0`` (``BT0`` in the wiring table, below) is the middle pin of the
outer three-pin boot jumper, it's next to pin B10. You need to remove the
jumper of course.

Connect all Bus1 to Bus3 lines, and add one of the 10k resistors to each.
The other end of the resistor goes to one of the Pills' 3.3 outputs.

RX1 to RX3 are the serial adapters' Rx pins. Likewise for Tx. Don't set the
adapters to 5V; the Pills are supposed to be able to take it, but it's
better not to require them to. Also, connect the serial adapters to the
same Pi you power the pills from.

====  == === === ===
GPIO  Pi   A   B   C
====  == === === ===
GND    6   G   G   G
5V     2  5V  5V  5V
====  == === === ===
  18  12 CLK
  23  16 SIO
  24  18   R
  21  40 BT0
 RX1  10  A9
 TX1   8 A10
====  == === === ===
   6  31     CLK
   5  29     SIO
  27  13       R
  20  38     BT0
 RX2          A9
 TX2         A10
====  == === === ===
  13  33         CLK
  12  32         SIO
  17  11           R
  16  36         BT0
 RX3              A9
 TX3             A10
====  == === === ===
Bus1     B12 B12 B12
Bus2     B13 B13 B13
Bus3     B14 B14 B14
Bus4     B15 B15 B15
====  == === === ===


-------
Testing
-------

The standard test consists of a serial bus gateway (pill A) and two slaves
(B and C). The gateway talks to a Python program that sends the incoming
messages to MQTT and vice versa. (This helps with debugging because it's
easy to record and replay messages.)

If you need to modify the test configuration, it's best to copy the ``ci/cfg``
someplace. Then do ``export CFG=/home/moatbus-test/cfg`` after starting
each terminal in the samples below.

Running the test
----------------

Start an MQTT server if you don't run one anyway.

On the Pi, start three terminals. Run ``ci/run a``, ``ci/run b`` and ``ci/run c``
in each, respectively.

The Makefile should copy ``prog.bin`` and ``gate.bin`` to the Pi.
Start ``ci/test``, which programs the three pills and then tells the
``test_X`` scripts to run a serial terminal (except for ``test_a``, which
runs the serial/MQTT gateway).

You should now see some messages as the three pills try to acquire
a MoaT bus address.

Start
