==============
Using DistGPIO
==============

Run "distkv client gpio monitor" to connect to the server on localhost.

See "distkv dump cfg gpio" for configuration options.

Data structure
==============

On disk, the path to the port is ".distkv gpio SERVER TYPE CARD PORT" by
default. All attributes are also looked up in the higher nodes, so you can
set per-type or per-server defaults easily.

Server attributes
+++++++++++++++++

* server: a dict with host and port. Set by ``distkv client gpio server``.

* poll: The cylce time of the controller. Typical: 0.05 seconds.

* ping: The interval between keep-alive messages from the controller.
  Typical: a few seconds.

Port attributes
+++++++++++++++

* mode: a string. Allowed values and their meaning depend on the port's
  type.

* low: Flag whether the line is inverted / active-low. Default False.

``input`` ports
---------------

Input ports are deemed dirty, i..e. they'll be de-bounced.

The premise is that the host system has a GPIO interrupt. Thus a pin change
interrupts the CPU, which then reads the port register, but at that time the
state might have flipped back.

Thus, AsyncGPIO's code does not trust the event's value until another
``debounce`` seconds have passed without a change, at which time the last
event's value is deemed to be authoritative.

There is also a ``skip`` flag that tells AsyncGPIO whether "dirty" signals, i.e. those
that bounce around for longer than ``t_bounce`` but then settle on the original
level, should be ignored. The default is ``True``.

read
~~~~

The current value of a wire on the controller is mirrored to some DistKV entry.

* dest: the path to store the result at.

* t_bounce: min length of a single signal, seconds, default 0.05

* skip: flag whether to ignore noisy signals (i.e. signals where all changes shorter than t_bounce)

* low: flag whether the wire's normal state is inverted.

count
~~~~~

The number of transitions of a wire on the controller is mirrored to some DistKV entry.

* dest: the path to save the counter to.

* t_bounce: min length of a single signal, seconds, default 0.05

* count: Flag whether to count L>H transitions (True), H>L (False) or both (None).

* interval: The time after which the counter is flushed, to avoid overwhelming the system when impulses arrive too fast.

The first transition after more than ``interval`` seconds without change have passed
is always signalled directly,
then changes are accumulated and sent every ``interval`` seconds.

button
~~~~~~

A sequence of (debounced) button presses. Reports the length of the signals in units of 't_bounce'.

* dest: the path to save the result to.

* t_bounce: min length of a single signal, seconds, default 0.05

* t_idle: return after this time without change, default 1.5 seconds

* t_idle_on: return after this time "on" without change, default to ``t_idle``.

* t_clear: after this time, the destination value will be cleared and replaced with ``False``.
  (``None`` is not used because that should be reserved for when the input is not available.)

* skip: flag whether to ignore noisy signals (i.e. signals where all changes shorter than t_bounce)

* low: flag whether the wire's normal state is inverted.

* flow: send messages as the button sequence progresses.

* count: Flag whether to measure H states (True), L states (False) or both (None).

Multiple interleaved buttons are not yet supported.


``output`` ports
----------------

write
~~~~~

The current value of some DistKV entry is mirrored to a wire on the controller.
Also, the current output state is mirrored to a "state" entry in DistKV.

* src: the path to monitor the valoe of.

* rest: Flag whether the line is inverted / active-low. Default False.

* state:

oneshot
~~~~~~~

The current value of some DistKV entry is mirrored to a wire on the controller for some time (max).
Also, the current output state is mirrored to a "state" entry in DistKV.

The wire is cleared when the time has passed, or when the DistKV entry is set to `False`.

* src

* rest

* state

* t_on: seconds the signal should be on.

  This can be a float or a tuple, in which case the value will be read from
  that location.

pulse
~~~~~~~

If some DistKV entry is set, a wire on the controller flips between on and
off. The "on" ratio is mirrored to a "state" entry in DistKV.

The wire is cleared (and the state entry set to zero) when the DistKV entry is set to `False`.

* src
* src

* rest

* state

* t_on

* t_off: seconds the signal should be off.

  This can be a float or a tuple, in which case the value will be read from
  that location.


Command line
============


.. program:: distkv client gpio

The main entry point for this extension.


.. program:: distkv client gpio port

Print or modify port settings.

This is a shortcut for ``… attr`` that evaluates various attributes and
lets you easily change more than one at a time.

.. option:: -m, --mode MODE

   Set the port's mode. See help text for known modes.

   Allowed modes depend on the type of the input or output.

.. option:: -a, --attr name value

   Adds an attribute. This option converts ``value`` to a tuple (if it
   contains spaces), integer or float (if possible).

   This option can be used more than once.

.. option:: path

   The path to the port to be modified. Must be "SERVER CARD PORT"
   (without quotes).
   The port is numeric, starting with 0.


.. program:: distkv client gpio attr

Print, modify or delete a single attribute.

If you set a value that is evaluated to a mapping, exising values will be merged.

.. option:: -a, --attr NAME

   The name of the attribute to display, change, or delete. Use more than
   once for nested values.

   Default: show all attributes.

.. option:: -v, --value VALUE

   The new value of the attribute.

   Do not forget ``-e`` if the value is numeric!

.. option:: -e, --eval

   The attribute's value is a Python expression.

   To delete an attribute, use ``--eval`` without ``--value``.

.. option:: -s, --split

   The attribute's value is a space-separated list of names.

   If the list contains actual numbers, you need to use a Python expression
   and "--eval".

.. option:: path

   The path to the port to be modified. Must be "SERVER CARD PORT"
   (without quotes).
   The port is numeric, starting with 0.


.. program:: distkv client gpio list

Print the current state of your GPIO controllers.

This command does not access the device; it is used solely for displaying
the configuration of the interaction with DistKV.

.. option:: server

   The server to access.

.. option:: controller

   The GPIO controller to access.

.. option:: type

   The type of connection. Currently supported: ``input`` and ``output``
   for 24 volt controls.

.. option:: card

   The card number. The first card should be 1 (assuming that it's recognized).

.. option:: port

   The port number. Ports are numbered starting with 1.


.. program:: distkv client gpio monitor

This is a stand-alone GPIO monitor. It connects to a single controller
and runs polls and monitors.

.. option:: name

   The system's name, i.e. the server name you've been using in "… gpio 
   server.

.. option:: controller…

   The controller[s] to connect to. You can't run this more than once for
   any given controller. Default: all controllers; note that new
   controllers are not picked up automatically. (TODO.)


