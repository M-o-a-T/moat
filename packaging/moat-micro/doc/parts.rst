====================
MoaT hardware access
====================

++++++
Basics
++++++

--------
part.Pin
--------

A simple hardware pin (for some value of "simple").

Commands
========

r
++

Read the pin, No arguments; returns a simple `True` or `False`.

w
++

Write the pin. The parameter `v` should be either `True` or `False`. Some
hardware also supports `None` for high-impedance ("floating") output.

it
++

This iterator will return a new result every time the pin's value changes.

sign
++++

A parameter that states which changes are significant for ``chg``. E.g. on
an interrupt wire, typically only the off-to-on transition is of interest.

chg
+++

One-shot wait for a pin change. If ``sign`` is `False` or `True`, only changes to
that value trigger this.

The optional parameter `v` contains the previous value.


Config
======

pin
+++

This value tells *which* pin to use. This is hardware specific but usually
they're simply numbered.

irq
+++

If the pin is behind an I²C device, pin changes typically are signalled
with a directly-connected wire that triggers an interrupt. This path
specifies the pin to wait for.

inv
+++

If ``True``, the pin's sense is inverted from the hardware.

dir
+++

Direction. ``True`` = output.

pull
++++

Pull-up/down resistors. Zero: floating. Positive: pull-up, negative:
pull-down. Increasing absolute values indicate higher relative strength.

Not all combinations are supported by all hardware.


----------
part.Relay
----------

Relays are output-only pins which are restricted from switching too quickly.

Commands
========

r
++

Read the relay state. A map with ``v`` (regular value), ``f`` (forced
value) and ``d`` (delay in msec until the regular value is switched to).

w
++

Set the relay state. ``v`` says which state to set to. ``f`` overrides
``v`` and applies immediately.

Config
======

Remember that names with dots are actually sub-dicts, thus::

    rly:
        pin: !P p.out10
        t:
            on: 5000
            off: 1000
            init: 10000


pin
+++

The path to the Pin object controlled by the relay.

t.on
++++

Delay before the relay may be turned on (again).

t.off
+++++

Delay before the relay may be turned off (again).

t.init
++++++

Startup delay, e.g. to charge a capacitor.

pwm
+++

PWM output, for saving power. Parameters are ``a`` and ``b`` for on and off
times in milliseconds, and ``i`` for the fixed on-time before the PWM starts.

enable
++++++

Path to an enabling pin. The pin will be cleared set after ``t.init`` has passed and cleared on shutdown.

