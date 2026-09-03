# MoaT hardware access

## Basics

### part.Pin

A simple hardware pin (for some value of "simple").

#### Commands

##### r

Read the pin, No arguments; returns a simple
<span class="title-ref">True</span> or
<span class="title-ref">False</span>.

##### w

Write the pin. The parameter <span class="title-ref">v</span> should be
either <span class="title-ref">True</span> or
<span class="title-ref">False</span>. Some hardware also supports
<span class="title-ref">None</span> for high-impedance ("floating")
output.

##### it

This iterator will return a new result every time the pin's value
changes.

##### sign

A parameter that states which changes are significant for `chg`. E.g. on
an interrupt wire, typically only the off-to-on transition is of
interest.

##### chg

One-shot wait for a pin change. If `sign` is
<span class="title-ref">False</span> or
<span class="title-ref">True</span>, only changes to that value trigger
this.

The optional parameter <span class="title-ref">v</span> contains the
previous value.

#### Config

##### pin

This value tells *which* pin to use. This is hardware specific but
usually they're simply numbered.

##### irq

If the pin is behind an I²C device, pin changes typically are signalled
with a directly-connected wire that triggers an interrupt. This path
specifies the pin to wait for.

##### inv

If `True`, the pin's sense is inverted from the hardware.

##### dir

Direction. `True` = output.

##### pull

Pull-up/down resistors. Zero: floating. Positive: pull-up, negative:
pull-down. Increasing absolute values indicate higher relative strength.

Not all combinations are supported by all hardware.

### part.Relay

Relays are output-only pins which are restricted from switching too
quickly.

#### Commands

##### r

Read the relay state. A map with `v` (regular value), `f` (forced value)
and `d` (delay in msec until the regular value is switched to).

##### w

Set the relay state. `v` says which state to set to. `f` overrides `v`
and applies immediately.

#### Config

Remember that names with dots are actually sub-dicts, thus:

    rly:
        pin: !P p.out10
        t:
            on: 5000
            off: 1000
            init: 10000

##### pin

The path to the Pin object controlled by the relay.

##### t.on

Delay before the relay may be turned on (again).

##### t.off

Delay before the relay may be turned off (again).

##### t.init

Startup delay, e.g. to charge a capacitor.

##### pwm

PWM output, for saving power. Parameters are `a` and `b` for on and off
times in milliseconds, and `i` for the fixed on-time before the PWM
starts.

##### enable

Path to an enabling pin. The pin will be cleared set after `t.init` has
passed and cleared on shutdown.

### part.Triac

A triac is a solid-state switch for AC loads.  Once triggered, a triac
conducts until the next natural zero crossing of the AC supply — there
is no way to actively turn it off.  Power is controlled by **phase-angle
triggering**: after each zero crossing the gate is pulsed after a delay
proportional to `(1-val)` of the half-cycle period.  At 100 % the gate
is held on continuously; at 0 % it is never fired.

This part is MicroPython-only.  It uses a hardware interrupt on the
zero-crossing input pin (recording microsecond timestamps) and a
hardware `Timer` to fire the gate pulse at the correct phase angle.
The line frequency is measured adaptively from the zero-crossing
timestamps, with glitch rejection via a median filter.

A zero-crossing detector input pin is **required**.

#### Commands

##### r

Read the triac state. A map with `v` (set value, float 0..1), `f`
(forced value), `p` (actual gate pin state, bool), and `h` (measured
half-cycle period in microseconds).

##### w

Set the triac power. `v` is a float in [0..1]. `f` overrides `v` and
applies immediately.

#### Config

    triac:
        pin: 20
        zero: 0
        invert: false
        zc_edge: 0
        timer: 1
        pulse: 100
        cycle: 20

##### pin

Gate output pin number.

##### zero

Zero-crossing detector input pin number.  **Required.**  The pin's
interrupt records microsecond timestamps used for phase-angle timing
and line-frequency estimation.

##### invert

If `True`, the gate output is inverted (active-low).

##### zc_edge

Which edge to trigger the ZC interrupt on: `0` = falling (default),
`1` = rising, `2` = both.

##### timer

Hardware timer number for the gate pulse (default 1).

##### pulse

Gate pulse width in microseconds (default 100).  The gate is turned on
for this duration and then off again, unless the triac is at 100 %.

##### cycle

Nominal AC cycle period in milliseconds (default 20, i.e. 50 Hz).
Used as an initial estimate only; the actual frequency is measured
from ZC interrupts.
