# Using DistOWFS

Run "moat kw ow monitor" to connect to the server on localhost.

See "moat dump cfg owfs" for configuration options. Specifically, use
this config snippet to connect to two external servers instead of
localhost:

    owfs:
      server:
        - host: one.example
        - host: two.example

## Command line

<div class="program">

moat kw ow

</div>

The main entry point for this extension.

<div class="program">

moat kw ow list

</div>

Print the current state of your 1wire devices.

This command does not access the device or show on which bus it is; this
is solely for displaying the configuration of its interaction with
DistKV.

<div class="option">

family

You can limit the display to a family code.

</div>

<div class="option">

device

If you add the device ID, only that devices data is displayed.

Use '-' to show the data stored at the family entry.

</div>

<div class="program">

moat kw ow monitor

</div>

This is a stand-alone 1wire monitor. It connects to all configured
servers and runs polls and monitors.

No options yet.

<div class="program">

moat kw ow poll

</div>

Configure polling.

If the device (and the given attribute) supports simultaneous
conversion, this might cause results to be read more often than
configured here.

<div class="option">

-f, --family \<code\>

Change the poll interval's default for this family code.

</div>

<div class="option">

-d, --device \<family.device\>

Change the poll interval for this device.

</div>

<div class="option">

\<attribute\>

Set the interval on this attribute. Use a `/` separator for
sub-attributes.

</div>

<div class="option">

\<interval\>

The interval to poll at. Use `-` to disable polling.

</div>

<div class="program">

moat kw ow set

</div>

You can use this command to add arbitrary values to a device's entry.
Use this e.g. to add a note where the device is located, or to signal
your own code.

<div class="option">

-f, --family \<code\>

Change an attribute on this family code.

</div>

<div class="option">

-d, --device \<family.device\>

Change an attribute on this device.

</div>

<div class="option">

-v, --value

The value to set.

</div>

<div class="option">

-e, --eval

Flag that the value is a Python expression and should be evaluated.

</div>

<div class="option">

\<name\>…

The attribute name to set. Use more than once for accessing sub-dicts.

</div>
