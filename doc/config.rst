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

Config
++++++

Create a Unix-domain port and listen to it. Used mainly for connecting
command line clients.

port
----

The path of the socket. Required. Prefixed with ``XDG_RUNTIME_DIR`` (or ``/tmp``) if relative.

replace
-------

  Action when there is more than one connection to the port. The value is
  expected to be a boolean. If `True` a new connection replaces the old
  one; all open requests are re-sent. If `False` the new connection is
  rejected with an error broadcast.

  If `None` (the default), multiple connections are allowed. In this case,
  individual links are numbered. Accessing the link via the application's
  path is not possible.

wait
----

  Action when there is no open connection. If `False`, raise an exception;
  otherwise wait for a new link.

  A numeric value specifies how long to wait until returning an error.

  This parameter is ignored when ``replace`` is `None`.

fatal
-----

  Flag whether to raise an exception if the link closes (and is not
  re-established within ``wait`` seconds, if that is not `False`).

Commands 
++++++++

None so far.

net.unix.Link
=============

Connect to a Unix-domain port. Used mainly for testing.

Config
++++++

port
----

The path of the socket. Required. Prefixed with ``XDG_RUNTIME_DIR`` (or ``/tmp``) if relative.

wait
----

  Timeout for messages sent to the link when there is no open connection.
  A numeric value specifies how long to wait until returning an error.

  If `False` or zero, immediately raise an exception; `True` retries
  indefinitely.

* fatal

  Flag whether to raise an exception if the link closes (and cannot be
  re-established within ``wait`` seconds, if that is not `False`).

  Ignored when `wait` is `True`.


net.pipe.Process
================

Start a process and connect to its standard input and output.

Config
++++++

command
-------

An array with the command's name and arguments.

Mandatory of course.

path
----

Path to the command. If not given, the command's first element is used.

frame
-----

SerialPacker configuration. See below.


net.ip.Port
===========

Connect to an IPv4 TCP port.

Config
++++++

address
-------

  The address to connect to. The default is ``localhost``.

port
----

  The port number to connect to. Required.

Other parameters
----------------

All other parameters are as in ``net.unix.Port``.


net.ip.Link
===========

Create an IPv4 TCP socket and listen to it.

Config
++++++

address

  The address to bind to. The default is ``localhost``.

port

  The port number to bind to. Required.

Other parameters
----------------

All other parameters are as in ``net.unix.Link``.


fs
==

This application affords basic file system access. It is used to access
files stored on embedded clients.

There currently is no implementation for servers, as network file systems
(NFS, CIFS) perform much better than a MoaT server.

Config
======

path
----

  The prefix to use.

readonly
--------

  Flag, defaults to `False`. If `True`, write access is rejected.

Commands
++++++++

reset
-----

Close all open files.

* p

  New path for this file system. Appended to the currently-set root if relative.

No return value.

open
----

Open a file. Returns a file handle.

* p

  Path of the file.

* m

  File mode. 'r or 'w', or possibly 'a'.

  Files are always opened in binary mode.
  
rd
--

Read a file.

* f

  A valid file handle.

* off

  Read offset. Must be positive, defaults to zero.

* n

  Number of bytes to read. The default is 64.

Return value: the bytes read.

wr
--

Write to a file.

* f

  A valid file handle, opened for writing.

* data

  The bytes to be written.

* off

  Write offset. Must be positive, defaults to zero.

Return value: the number of bytes written.

cl
--

Close a file.

* fd

  A valid file handle.

dir
---

List a directory.

* p

  Path to the directory to be enumerated.

* x

  Flag for extended output.

Return value: a list of entries. ``.`` and ``..`` are not returned.

If ``x`` is False, the file names are returned directly. Otherwise, each
value is a map with these entries:

* n

  Name of the file

* t

  Modification timestamp

* s

  File status flags

mkdir
-----

Create a directory.

* p

  The path of the new directory.

hash
----

Return the ``sha256`` of a file's contents.

* p 

  The path to the file to be hashed.

Return value: The hash value, as 32 bytes.

stat
----

Return the status of a file.

* p

  The path to the file or directory to be probed.

Return value: a dict of

* m

  File mode: 'd' or 'f'

* s

  File size. Not used for directories.

* t

  Modification time.

* d

  Status array.

mv
--

Rename a file.

* s

  Source path.

* d

  Destination path.

* x

  If set, used as a temporary file name to exchange the files.

* n

  Flag whether the destination must not exist.

``n`` and ``x`` are mutually exclusive.

rm
--

Delete a file.

* p

  Path to the file to delete.

rmdir
-----

Delete a directory.

* p

  Path to the directory to delete.

The directory must be empty.

new
---

Create a file.

* p

  Path to the file to create

The new file is *not* opened for writing by this command.


serial.Cmd
==========

Access to a serial port.

The 

Config
++++++

port
----

  The port to use. Typically a number.

tx, rx
------

  Pins to use, if they need to be specified.

rate
----

  Baud rate.

stop
----

  Flag whether to send two stop bits. Defaults to `False`. If `None`, 1.5
  stop bits are used (if supported).

parity
------

`True`: odd parity, `False`: even parity. The default is `None` for no parity bit.

bits
----

The default is 8. Other values may or may not be supported.

frame
-----

SerialPacker configuration. If this element is missing or `None`, no
framing is performed; trying to send a packet will result in an error.

Otherwise this should be a map with these entries:

* idle

  Inter-packet timeout im milliseconds. Default: 100.

* max

  Max packet length. The default is 127.

* frame

  Frame start byte. The default is 0x85. `None` relies on inter-frame
  timing and does not allow non-framed data unless you use a mark byte.

  This byte should not occur in standard console output. The frame receiver
  understands UTF-8 sequences, thus the range 0x80…0xBF is safe to use.

* mark

  Every byte that's part of a frame *must* be prefixed with a ``mark``
  byte. Other bytes are transmitted as-is. There is no provision for
  escaping. A mark byte like "DLE" (0x10) should be used that will not
  occur in normal console output.


dest
----

The destination for received packetized data, i.e. the content of valid
SerialPacker frames.

The destination command receives the serial data as a single non-keyword
argument.

If no destination is set, the message is discarded. TODO: implement a
buffer.

dest_raw
--------

like ``dest`` but for received non-packetized data, i.e. bytes received
outside of SerialPacker framing.

Commands
++++++++

send
----

Transmit a packet of data.

* data

  The bytes to send.

* raw

  Flag whether to send the bytes directly.

  Otherwise the dara are encapsulated in a SerialPacker frame.

The commands ``x`` ("xmit") and ``w`` ("write") are aliases for ``send``
with the ``raw`` flag cleared and set, respectively, in order to save
a couple of bytes when talking to a remote serial port.

errcount
--------

Returns the number of transmission errors encountered so far.

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

