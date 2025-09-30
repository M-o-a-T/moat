==========================
The MoaT Battery Scheduler
==========================

This module implements a scheduling algorithm for a photovoltaic system
with battery. It considers varying projected PV gain, local load, and
buy/sell prices for grid power.

+++++++++
Operation
+++++++++

The standalone program is started with the command `moat ems sched analyze`.
Use `--help` for usages.

++++++++
Channels
++++++++

`moat ems sched analyze` reads the data it needs from a variety of possible
channels. Likewise, it sends its output to them.

Data per interval
+++++++++++++++++

load
----

The internal load, in kW.

Source: You should extrapolate from past system behavior. This is where a
neural network might be a good idea.

.. Note:: time-of-day and day-of-week inputs to a neural net should be cyclic,
   i.e. instead of one input you use two, with sin(X*2*pi) and cos(X*2*pi)
   as X goes from 0 to 1.

One value per interval.

solar
-----

The projected solar yield, in kW.

Source: Calculate from weather forecast and solar array positioning.
There are services that do this for you.

One value per interval.

price_sell
----------

Price you get per kW you sell to the grid. Depending on your contract
this value might be fixed, set some time in advance, or maybe you need to
extrapolate from past prices.

One value per interval.

price_buy
---------

The cost per kW you buy from the grid.

As "price_sell". There's a mode that calculates buy from sell price.

One value per interval.

Fixed data
++++++++++

soc
---

The charge in your battery which your calculation starts off with.

Outputs
+++++++

Output data contain these values:

* grid: power to feed to / pull from the grid
* soc: projected battery state-of-charge at the end of the interval
* batt: power to feed to / pull from the battery
* money: income / cost during this interval

result
------

Data for the first interval is sent to this channel. You typically use this
to control your inverter.

results
-------

This channel receives projected data for all intervals. You typically use
this to display a nice graph.


+++++++++++++
Configuration
+++++++++++++

MoaT uses a YAML-based configuration.

`moat ems sched dump` prints the config data. You can modify it in three
ways:

* add your config data to your global MoaT configuration::

    ems:
        sched:
            solar:
                lat: 50.2
                long: 11.8

* load a config file with `moat ems sched -c ‹path›`::

    solar:
        lat: 50.2
        long: 11.8

* modify the configuration from the command line::

    moat ems sched -e solar.lat 50.2 -e solar.long 11.8

There's an `-e` and a `-v` option. The former is evaluated, i.e.
used for numerical values, while the latter is not (text, file paths).

Later values override earlier ones.

Sources
+++++++

This section concerns both sources (i.e. ways to get data into the
scheduler) and sinks (ways to get them back out).

You can use `moat ems sched modes` to list the scheduler's supported inputs
and outputs. Each mode supports a subset of data sources.

You configure which input/output to use with the `mode.‹channel›`
configuration. Thus, to load the read the SoC from a file you'd use::

    mode:
        soc:
            file
    data:
        file:
            soc: "/path/to/whereever.cvs"

or, equivalently,
`moat ems sched -v mode.soc file -v data.file.soc /path/to/whereever.cvs analyze`.

file
----

Source for per-interval data. Files consist of lines with one float number
each. There's no support for comments, blank lines, or other fanciness.

file2
-----

Source for `price_buy` that's derived from `price_sell`.

stdout
------

YAML data for either the first result results



Config hints
++++++++++++

Panels
------
Your solar array can have multiple groups of panels.

Battery
-------
The `battery.soc.value.current` and `battery.soc.value.end` configurations
assign a value to a full battery, during / at the end of the simulation.

This tells the simulator that you want to keep the battery charged, and
prevents it from draining the battery for the monetary value of its energy.
This is a real problem for short simulation runs.

Best results if the "end" value is somewhere between the buy and sell
price of the battery's energy. The "current" value should be smaller;
it biases the system towards keeping the battery charged.

The simulator tolerates when you start off with a SoC that's outside of the
min/max range, but it (currently) will force the battery to be in that
range during the first time slot. Fixing this is planned.


+++++++++
Algorithm
+++++++++

The scheduler uses a simple linear optimizer (for some value of "simple" …)
based on Google's OR Tools. It models a DC-connected battery and solar
array.

++++
TODO
++++

Modeling an AC-connected solar array is straightforward but hasn't been implemented yet.

Currently we're using a linear optimizer. There are a heap of non-linear
extensions that would really improve the simulation:

* Grid power that becomes more expensive beyond a threshold

* inverter/charger/battery efficiencies that depend on the load

* Inverter efficiency decreases when it runs on high load for too long
  (needs cooling).

* the maximum battery charge/discharge power decreases when close to the
  top/bottom of SoC

* support discretionary loads (e.g. an electric car that requires 4h of max
  power to be charged, and you need it to be fully charged by tomorrow
  evening)

* some discretionary loads can be interrupted (electric car); others can't
  (oven, washing machine).

* some discretionary loads are intermittent; e.g. a heat pump with an
  8-hour buffer that can be "recharged" by running the pump for three hours.
  (Efficiency might depend on outside temperature.)

* some discretionary loads are less efficient when not running on full
  power. E.g. the car might take 9h to charge at half load because of charger
  inefficiency and/or because it consumes some power when it's turned on.

* some loads require reactive power; some older electric cars, like the 1st
  gen Renault Zoë, are notorious for this. If you run such a load while
  offsetting local consumption from PV or battery, the result is that you
  send all that reactive power to the grid, with a cos(φ) of (close to)
  zero. This may or may not be allowed.

* In some countries you get subsidized for the energy you sell to the grid
  so that you earn more than you'd pay when you buy it. This has a couple
  of implications:

  * Obviously you can't sell and buy power at the same time.

  * The control algorithm needs to remember how much of the battery's
    energy has been imported from the grid; it must not feed that energy
    back to the grid.

  * Using energy from the PV array to power local loads de-contaminates the
    battery even if the SoC doesn't change: It's conceptually the same as
    taking energy from the battery, then recharging the battery from solar.


There are several services that supply weather and PV forecasts. They
should be supported.

Batteries don't want to be fully charged / discharged for too long. We want
the scheduler to avoid that.

Some batteries need regular balancing. We want the scheduler to prefer to
fully charge the battery weekly, and force it to do so every 20 days.
(Numbers are an example.)
