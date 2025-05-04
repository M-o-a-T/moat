=================
Using MoaT-KV-KNX
=================

Run "moat kv knx monitor" to connect to the server on localhost.

See "moat kv dump cfg kv.knx" for configuration options.

Data structure
==============

On disk, the path to a KNX group address is ".knx.BUS:A:B:C" by
default. All attributes are also looked up in the higher nodes, so you can
set per-line or per-server defaults easily.

Server attributes
+++++++++++++++++

* server: a dict with host and port. Set by ``moat kv knx server``.

* poll: The cylce time of the controller. Typical: 0.05 seconds.

* ping: The interval between keep-alive messages from the controller.
  Typical: a few seconds.

Port attributes
+++++++++++++++

* mode: a string. Allowed values and their meaning depend on the port's
  type.

``input`` ports
---------------

read
~~~~

The current value of a wire on the controller is mirrored to some MoaT-KV entry.

* dest: the path to store the result at.

* rest: Flag whether the line is inverted / active-low. Default False.

count
~~~~~

The number of transitions of a wire on the controller is mirrored to some MoaT-KV entry.

* dest: the path to store the counter at.

* count: Flag whether to count L>H transitions (True), H>L (False) or both (None).

* interval: The time after which the counter is flushed, to avoid overwhelming the system when impulses arrive too fast.

``output`` ports
----------------

write
~~~~~

The current value of some MoaT-KV entry is mirrored to a wire on the controller.
Also, the current output state is mirrored to a "state" entry in MoaT-KV.

* src: the path to monitor the valoe of.

* rest: Flag whether the line is inverted / active-low. Default False.

* state:

oneshot
~~~~~~~

The current value of some MoaT-KV entry is mirrored to a wire on the controller for some time (max).
Also, the current output state is mirrored to a "state" entry in MoaT-KV.

The wire is cleared when the time has passed, or when the MoaT-KV entry is set to `False`.

* src

* rest

* state

* t_on: seconds the signal should be on.

  This can be a float or a tuple, in which case the value will be read from
  that location.

pulse
~~~~~~~

If some MoaT-KV entry is set, a wire on the controller flips between on and
off. The "on" ratio is mirrored to a "state" entry in MoaT-KV.

The wire is cleared (and the state entry set to zero) when the MoaT-KV entry is set to `False`.

* src

* rest

* state

* t_on

* t_off: seconds the signal should be off.

  This can be a float or a tuple, in which case the value will be read from
  that location.


Command line
============


.. program:: moat kv knx

The main entry point for this extension.


.. program:: moat kv knx port

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

   The path to the port to be modified. Must be "SERVER TYPE CARD PORT".
   Card and port are numeric, starting with 1.


.. program:: moat kv knx attr

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


.. program:: moat kv knx list

Print the current state of your KNX controllers.

This command does not access the device; it is used solely for displaying
the configuration of the interaction with MoaT-KV.

.. option:: server

   The KNX controller to access. By default MoaT-KV-KNX uses tunneling.

.. option:: group1

   Group address 0…15.

.. option:: group2

   Group address 0…15.

.. option:: group3

   Group address 0…255.


.. program:: moat kv knx monitor

This is a stand-alone KNX monitor. It connects to a single controller
and runs polls and monitors.

.. option:: server

   The controller to connect to. Do not run this more than once for any given
   server.



Configure polling.

If the device (and the given attribute) supports simultaneous conversion,
this might cause results to be read more often than configured here.

.. option:: -f, --family <code>

   Change the poll interval's default for this family code.

.. option:: -d, --device <family.device>

   Change the poll interval for this device.

.. option:: <attribute>

   Set the interval on this attribute. Use a ``/`` separator for sub-attributes.

.. option:: <interval>

   The interval to poll at. Use ``-`` to disable polling.


.. program:: moat kv knx set

You can use this command to add arbitrary values to a device's entry. Use
this e.g. to add a note where the device is located, or to signal your own
code.

.. option:: -d, --device <family.device>

   Change an attribute on this device.

.. option:: -v, --value

   The value to set.

.. option:: -e, --eval

   Flag that the value is a Python expression and should be evaluated.

.. option:: -s, --split

   Flag that the value is a multi-word string and should be split.

.. option:: <name>…

   The attribute name to set. Use more than once for accessing sub-dicts.

