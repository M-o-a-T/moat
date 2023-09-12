==========================
The MoaT.micro config file
==========================

Configuring MoaT.micro is accomplished with a YAML file.

This file describes the config file's sections and their usage.

--------
Overview
--------

This section offers a brief overview about the sections of the MoaT-micro
configuration and their uses.

apps
====

This section lists the applications that this multiplexer is running.

This is a simple dict, mapping from a unique name to the class that
implements the application. Class names are relative to "moat.micro.app"
(on servers) or "app" (on MCUs).

By convention, classes named "Link" connect to remote systems; classes
named "Port" allow multiple connections by external tools. App names
are typically very short, in order to reduce communication overhead.

«app name»
==========

These sections contain the corresponding app's configuration data.

cfg
===

Subsections in this section contain the configuration data for a remote
system.

Consider this example::

    apps:
      s: serial.Link
    s:
      port: "/dev/ttyUSB0"
	  mode: &rs
        rate: 115200
    cfg:
      s:
        apps:
          wdt: wdt.Cmd
		  r: serial.Link
		  f: fs.Cmd
        r: 
		  port: 2
		  mode: *rs

Here, the top-level section ``s`` contains the data that describes how to
talk to the serial port. ``cfg.s`` is the configuration file that ``moat
micro setup`` will initially send to the remote side.

On the remote side, ``apps.r`` configures the MCU's serial link back to the
controlling system.

``s.mode`` is marked as shared data: both sides need to agree on
details like link speed and communication details, thus it's good practice
to not duplicate the data. This way you won't accidentally change just one
side's value and then wonder why nothing works any more …

setup
=====

This section lists parameters used by ``moat micro setup``, the program used for
initially copying the MoaT main program to the MCU.

.. note::

    While you can use ``setup`` to copy your apps onto the MicroPython
	machine, once MoaT is running it's usually easier to use the remote
	file system app.

connect
=======

This section is used by ``moat micro cmd`` to discover how to talk to a
multiplexer.

Consider this example::

    apps:
      pu: net.unix.Port
    pu: &ru
      port: "moat.fallback"
    connect:
      mode: unix
      unix: *ru

The ``pu`` app tells the multiplexer to open a Unix port for connectivity.
The client then uses the information from the ``connect`` section to open
this port.

------------
Applications
------------

net.unix.Port
=============

Create a Unix-domain port and listen to it. Used mainly for connecting
command line clients.

* port

  The path of the socket. Required. Prefixed with ``XDG_RUNTIME_DIR`` (or ``/tmp``) if relative.

* replace

  Action when there is more than one connection to the port. The value is
  expected to be a boolean. If `True` a new connection replaces the old
  one; all open requests are re-sent. If `False` the new connection is
  rejected with an error broadcast.

  If `None` (the default), multiple connections are allowed. In this case,
  individual links are numbered. Accessing the link via the application's
  path is not possible.

* wait

  Action when there is no open connection. If `False`, raise an exception;
  otherwise wait for a new link.

  A numeric value specifies how long to wait until returning an error.

  This parameter is ignored when ``replace`` is `None`.

* fatal

  Flag whether to raise an exception if the link closes (and is not
  re-established within ``wait`` seconds, if that is not `False`).


net.unix.Link
=============

Connect to a Unix-domain port. Used mainly for testing.

* port

  The path of the socket. Required. Prefixed with ``XDG_RUNTIME_DIR`` (or ``/tmp``) if relative.

* wait

  Timeout for messages sent to the link when there is no open connection.
  A numeric value specifies how long to wait until returning an error.

  If `False` or zero, immediately raise an exception; `True` retries
  indefinitely.

* fatal

  Flag whether to raise an exception if the link closes (and cannot be
  re-established within ``wait`` seconds, if that is not `False`).

  Ignored when `wait` is `True`.


net.ip.Port
===========

Connect to an IPv4 TCP port.

* address

  The address to connect to. The default is ``localhost``.

* port

  The port number to connect to. Required.

All other parameters are as in ``net.unix.Port``.


net.ip.Link
===========

Create an IPv4 TCP socket and listen to it.

* address

  The address to bind to. The default is ``localhost``.

* port

  The port number to bind to. Required.

All other parameters are as in ``net.unix.Link``.


fs
==

This application affords basic file system access. It is used to access
files stored on embedded clients.

There currently is no implementation for servers, as network file systems
(NFS, CIFS) perform much better than a MoaT server.

* path

  The prefix to use.

* readonly

  Flag, defaults to `False`. If `True`, write access is rejected.


serial.Cmd
==========

Access to a serial port.

* port

  The port to use. Typically a number.

* tx, rx

  Pins to use, if they need to be specified.

* rate

  Baud rate.

* stop

  Flag whether to send two stop bits. Defaults to `False`. If `None`, 1.5
  stop bits are used (if supported).

* parity

  `True`: odd parity, `False`: even parity. The default is `None` for no parity bit.

* bits

  The default is 8. Other values may or may not be supported.


wdt
===

The watchdog timer.

* hw

  Flag whether to use the hardware watchdog timer.

* t

  Watchdog timeout in seconds.

* tt

  Timer for periodically triggering the watchdog; defaults to ``t/2``.

* ext

  Flag whether a periodic external message is required. Note that the timer
  does start before the first message arrives, thus a too-small value of ``t``
  might cause the client to be non-recoverable.

wdt.ping
========

Server component to periodically reassure a remote watchdog.

* p

  Path to the remote watchdog timer.

* tt

  Timer for periodically sending a keepalive message, in seconds.

  Communication errors are ignored.

* t

  If set, raises an error if no watchdog reply arrives within this many
  seconds.

