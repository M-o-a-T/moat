# MoaT EMS

This module contains a collection of code related to energy management.

The basic setup assumed by these modules is that you have a DC battery, a
bidirectional inverter (one to three phases), photovoltaics, local demand,
and a grid connection.

## battery

The Battery Management System. It's a client-server, device-agnostic, and
supports multiple battery chemistries.

## inv

Inverter control. You can set the battery's intended charge and the
controller will get you there, subject to various constraints (battery max
charge and discharge current, inverter capabilities, but also "no feed-out
to the grid" or "no discharging the battery beyond 75%").

TODO: As a special case, this code also supports the case where feeding
power to the grid is subsidized. The scheduler implements fraud prevention,
by not send any energy to the grid which you previously got from it.

## sched

Energy use scheduling. Given possibly-variable prices for power (including
grid feed-out), variable PV output, and local demand, this code models
which strategy results in the lowest energy cost.
