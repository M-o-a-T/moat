==========================
The MoaT Battery Scheduler
==========================

This module implements a scheduling algorithm for a photovoltaic system
with battery. It considers varying projected PV gain, local load, and
buy/sell prices for grid power.

+++++++++
Operation
+++++++++

The standalone program is started with the command `moat bms sched`.
Run with `--help` for usage.

Input files consist of lines with single floating-point numbers
with the projected gain/load in Watt.

+++++++++++++
Configuration
+++++++++++++

MoaT uses a YAML-based configuration. All power values are per kW. Battery
capacity and prices are in / per kWh.

If you supply a single pricing schedule, the grid-in price is calculated
from grid-out by multiplying by ``pricing.factor`` (e.g. VAT) and adding
``pricing.surcharge`` (e.g. per-kWh network cost).

The default values, as stored in ``moat/bms/sched/config.yaml``:

.. yaml::

    bms:
        sched:
            pricing:
                # prices are per kWh
                in: 1
                out: 1
                factor: 1.2
                surcharge: 0
            capacity: 0  # must update
            battery:
                # on_ac: false  # TODO
                max:
                    charge: 5
                    discharge: 8
                efficiency:
                    charge: 0.95
                    discharge: 0.95
            inverter:
                max:
                    charge: 10
                    discharge: 10
                efficiency:
                    charge: 0.9
                    discharge: 0.9
            grid:
                max:
                    in: 99999
                    out: 99999

+++++++++
Algorithm
+++++++++

The scheduler uses a simple linear optimizer (for some value of "simple" …)
based on Google's OR Tools. It models a DC-connected battery.

++++
TODO
++++

Modeling an AC-connected battery is straightforward but hasn't been done yet.
