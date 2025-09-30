=========================
MoaT Application Handlers
=========================

Basically, a MoaT "app" is any code that hooks into a device's command dispatcher.

MoaT comes with a number of built-in apps.

Watchdog
========

The watchdog is responsible for rebooting the system if/when the hardware
gets wedged, or a fault causes the MoaT task to exit.

Hardware watchdogs typically are write-only: once set up, their mode or
timeout cannot be changed.

Configuration
+++++++++++++

hw
--

(bool)

Flag to use the hardware watchdog.

ext
---

(bool)

Flag to *not* poke the watchdog. This mode depends on periodic external
calls to cmd.``x``. thus rebooting the system whenever there is a
communication problem.
