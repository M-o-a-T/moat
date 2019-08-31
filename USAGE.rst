==============
Using DistWAGO
==============

Run "distkv client wago monitor" to connect to the server on localhost.

See "distkv dump cfg wago" for configuration options. Specifically, use
this config snippet to connect to two external servers instead of localhost::

   wago:
     server:
       - host: one.example
       - host: two.example


Command line
============


.. program:: distkv client wago

The main entry point for this extension.


.. program:: distkv client wago list

Print the current state of your Wago controllers.

This command does not access the device or show on which bus it is; this is 
solely for displaying the configuration of its interaction with DistKV.

.. option:: family

   You can limit the display to a family code.

.. option:: device

   If you add the device ID, only that devices data is displayed.

   Use '-' to show the data stored at the family entry.


.. program:: distkv client wago monitor

This is a stand-alone Wago monitor. It connects to all configured servers
and runs polls and monitors.

No options yet.


.. program:: distkv client wago poll

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


.. program:: distkv client wago set

You can use this command to add arbitrary values to a device's entry. Use
this e.g. to add a note where the device is located, or to signal your own
code.

.. option:: -f, --family <code>

   Change an attribute on this family code.

.. option:: -d, --device <family.device>

   Change an attribute on this device.

.. option:: -v, --value

   The value to set.

.. option:: -e, --eval

   Flag that the value is a Python expression and should be evaluated.

.. option:: <name>…

   The attribute name to set. Use more than once for accessing sub-dicts.

