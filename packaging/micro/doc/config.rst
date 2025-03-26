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

+++++++++++++++++++++
Generic configuration
+++++++++++++++++++++

MoaT-Micro uses a generic scheme for configuring its parts. In the config
file, this scheme is embodied in the "run", setup", and "client" sections.

It consists of a list of named applications that are to be started, and
per-app configuration. An app can run more than once, to connect to
different remote systems.

MoaT systems can be chained. A typical server might run a "sat:
net.unix.Port" app for client commands to connect to, and a "serial.Link"
app to talk to a remote system which in turn contains a "fs: fs.Cmd" app.
The client then uses a "m: net.unix.Link" app to talk to the main app.
This way it can use e.g. "m.sat.fs.open" to open a file on the satellite's
Flash file system.

apps
====

This section lists the applications that this multiplexer is running.

This is a simple dict, mapping from a unique name to the class that
implements the application. Class names are relative to the Python package
"moat.micro.app" (on Unix systems) or "app" (on MCUs running MicroPython).

By convention, classes named "Link" connect to remote systems; classes
named "Port" allow multiple connections by external tools. App names
are typically very short, in order to reduce communication overhead.

«app name»
==========

These sections contain the corresponding app's configuration data.


++++++++++++++++++++
Specific subsections
++++++++++++++++++++

cfg
===

This section contains the configuration data for remote systems.

Consider this example::

    setup:
      # ...
      config: !P cfg.sat
    run:
      apps:
        r: serial.Link
      r:
        port: "/dev/ttyUSB0"
        mode: &rs
          rate: 115200
        frame: 0xc1
    cfg:
      sat:
        apps:
          wdt: wdt.Cmd
          r: serial.Link
          f: fs.Cmd
        r: 
          port: 2
          mode: *rs
          frame: 0xc1

Here, the section ``run.r`` contains the data that describes how to
talk to the serial port. ``cfg.sat`` is the configuration file that ``moat
micro setup`` will initially send to the remote side.

On the remote side, ``apps.r`` configures the MCU's serial link back to the
controlling system.

``run.r.mode`` is marked as shared data: both sides need to agree on
details like link speed and communication details, thus it's good practice
to not duplicate the data. This way you won't accidentally change just one
side's value and then wonder why nothing works any more …


setup
=====

This section lists parameters used by ``moat micro setup``, the program used for
initially copying the MoaT main program to the MCU.

.. note::

    While you can use ``setup`` to copy code and data to the MicroPython
    machine, once MoaT is running it's easier / less disruptive to use the
    remote file system app.

The ``setup`` tool uses a serial or network connection and expects a MicroPython
console at the other end.

The default configuration requires a ``remote`` option.

remote
++++++

The path to reach the remote system.

The default is to use "r". More complicated setups are possible; e.g. you
can tunnel through a MoaT link and use one MoaT peripheral to program another.

args
++++

Other parameters for setup. See "moat micro setup --help"; the
configuration replaces dashes in the command line parameters with
underscores.

reset
-----

Perform a (soft) reset after uploading.

run
---

After uploading, start "moat run". This may or may not be incompatible with
``reset``.

source
------

Local path to copy files from. No files get copied if not given.

root
----

The root of the remote file system. Useful for updating the fallback system
if you don't use ``dest``.

dest
----

Path on the destination system where files shall be copied to.

The default is the source path, starting at the ``_embed`` subdirectory if
it exists.

state
-----

The MoaT system state to boot with.

You might want to use "once" for initial debugging.

verbose
-------

Start the target in verbose mode.


cross
-----

``mpy-cross`` compiler. If set, files ending in ``.py`` will be
cross-compiled and uploaded with an extension of ``.mpy``.

run
===

This configuration is used by "moat micro run". It typically includes apps
for all connected satellites, as well as one for a TCP and/or Unix socket.

connect
=======

This section lists parameters used by other ``moat micro`` subcommands (i.e. all except ``setup`` and ``run``) to talk to a MoaT system.

The standard content of this section is something like this:

    micro:
      connect:
        apps:
          r: net.unix.Link
        r:
          port: "Specify a Unix socket!"

        remote: !P r.s
        path:
          fs: !P f
          sys: !P _s
          cfg: !P _c

This means:

* connect to a ``moat micro run`` command that listens on this port
* and use its ``s`` subcommand (presumably a serial link) to talk to the remote.
* The remote's file, system, and config objects are thus reached via ``r.s.f``,
  ``r.s._s`` and ``r.s._c``, respectively.

More complicated setups are possible; for instance, you can tunnel through a
MoaT link and use one MoaT peripheral to directly talk to another.

You can omit the Path markers in the ``path`` section, but we don't recommend it.


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
individual links are numbered. A method to derive the link's path is
TODO.

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

link
----

Data framing and link configuration. See below.


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
-------

The address to bind to. The default is ``localhost``.

port
----

The port number to bind to. Required.

Other parameters
----------------

All other parameters are as in ``net.unix.Link``.


fs
==

This application affords basic file system access. It is used to access
files stored on embedded clients.

There currently is no implementation of this app for servers, as network
file systems (NFS, CIFS) perform much better than a MoaT server.


Config
++++++

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

* o

  Read offset. Must be positive, defaults to zero.

* n

  Number of bytes to read. The default is 64.

Return value: the bytes read.

wr
--

Write to a file.

* f

  A valid file handle, opened for writing.

* d

  The bytes to be written.

* o

  Write offset. Must be positive, defaults to zero.

Return value: the number of bytes written.

cl
--

Close a file.

* fd

  A valid file handle.

ls
--

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

* m

  file type ("d", "f", "?").

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

This app controls a local serial port. Some other MoaT component only needs
the path to that port to talk to it; whether the port is on a local system
or three links away is transparent (the latter is slower, obviously).


Config
++++++

port
----

The port to use. Typically a number (on satellites), or a path (on Unix).

tx, rx, rts, cts
----------------

Pins to use, if they need to be specified.

The default is port specific for ``tx`` and ``rx``, and no pin for the
others.

The RTS and DTR pins default to being enabled.

flush
-----

Timer for dropping spurious incoming characters after opening the port.
The default is 200 msec if `True`. Data trickling in extends the timeout.

txb, rxb
--------

Buffer sizes for transmit and receive. The default is 128 for each.


mode
----

Basic communication parameters.

rate
....

  Baud rate.

stop
....

  Flag whether to send two stop bits. Defaults to `False`. If `None`, 1.5
  stop bits are used (if supported).

parity
......

`True`: odd parity, `False`: even parity. The default is `None` for no parity bit.

bits
....

Number of bits. The default is 8. Other values may or may not be supported.

flow
....

Hardware flow control: "R" and/or "C" to use RTS / CTS. The default is neither.

rts_state, dtr_state
....................

State of RTS and DTR.

rts_flip, dtr_flip
..................

Flag whether RTS and/or DTR should be inverted briefly, when opening the
port.

dtr_rts
.......

The delay from setting or changing DTR to affecting RTS.

If negative, RTS is changed first.

The default is zero.

delay
.....

The initial delay between opening the port and affecting its wires.

The default is zero.

delay_flip
..........

The delay between initially flipping the wires and setting them to their
final configuration.

The default is 0.2 seconds.


link
----

Data framing and link configuration. See below.


cfg
===

Access to the configuration file.


r
--

Read part of the configuration.

A complex satellite device with small memory may have problems keeping
a serialized copy of its configuration in memory, let alone two, which is
necessary when building the bytestring for transmitting it.

Thus this method retrieves a config slice.

p
..

The path to the data to be retrieved, as a sequence of map keys.

The default is the empty path, i.e. the config root.

Result
......

Same as ``eval``.


w
--

Update part of the configuration.

This afects only the in-memory config data. The satellite's nonvolatile config 
is stored on its file system an can be accessed using the ``fs`` module.

p
..

Path to the destination. It cannot be empty.

d
..

Data to be put there. If ``NotGiven`` (or simply missing, though you
shouldn't depend on that), data at the destination is deleted.

Result
......

None.


x
--

Activates the new configuration.

This might be disruptive in that the connection used to send this command
may or may not be broken by it. The satellite will try to deliver the
confirmation before rebooting, but currently it does not guarantee that.


_sys
====

This app is installed by default. It cannot be configured.

Commands
++++++++

state
-----

MoaT devices have a state file in Flash or possibly NVRAM, which controls
what happens when the system ends, dies with an error, or the device is
reset due to watchdog or power failure.

state
.....

A simple string which, if set, replaces the previous state file.

Result
......

A map consisting of ``n``: the previous state, ``c``: the state when the
system was started, and ``fb``: a flag whether the current state is using
the fall-back MaoT stack and configuration.

test
----

This command builds and returns a test string, consisting of ``r CR n LF -
NUL c ^C e ESC !``. It is used to verify the integrity of the
communications line towards the server.

Use ``ping`` to verify consistency in the other direction.

eval
----

Evaluate an object / return its details. This call can be used to evaluate
a string, or to dig into the data held by a proxy.

x
..

The object to access. Strings are evaluated. Anything else (typically a
proxy) is used as-is.

p
..

The path to the data to be retrieved. The first element is an attribute of
the object; all others are map keys or list indices.

The path is ignored when an object is proxied to the remote side.

r
..

If set, returns ``repr(result)`` instead of the result itself.

The default is `False` though the caller should not depend on that.

Result
......

If the accessed element is a "simple" object, i.e. anything that's not a
map or a list, it is returned as-is (i.e. as a proxy object if it cannot be
serialized).

Maps and lists are returned as a two-element list: the original object,
stripped of non-simple members; and a list of map keys / offsets of the
removed members.

The caller is expected to recurse retrieval of the configuration.


unproxy
-------

Proxy objects represent data that cannot be serialized. They are kept
around, potentially cluttering memory.

Proxies should only be processed and generated by ``eval`` commands. Unless
expressly noted, no other command may return them. Sending a proxy to
anything other than an ``eval`` may result in unpredictable behavior.

p
..

The proxy object to be deallocated.


ping
----

m
...

The message to be echoed. Defaults to `None`.

Result
......

A map: ``m``, the message sent to it, and ``rep``: ``repr(m)``.


wdt
===

The watchdog timer, on the client side.

Config
++++++


hw
--

Flag whether to use the hardware watchdog timer.

t
--

Watchdog timeout in seconds.

tt
--

Timer for periodically triggering the watchdog; defaults to ``t/2``.

ext
---

Flag whether a periodic external message is required. Note that the timer
does start before the first message arrives, thus a too-small value of ``t``
might cause the client to be non-recoverable.


wdt.ping
========

Server component to periodically reassure a remote watchdog.

Config
++++++

p
--

Path to the remote watchdog timer.

tt
--

Timer for periodically sending a keepalive message, in seconds.

Communication errors are ignored.

t
--

If set, raises an error if no watchdog reply arrives within this many
seconds.


-------------------
Additional settings
-------------------

Data transport
++++++++++++++

MoaT-micro supports data links that are

* 100% reliable (serial data emulated over USB)

* randomly unreliable (e.g. serial data using a UART)

* deterministically unreliable (e.g. a TCP connection)

It also supports using the same link for packet data that's used as the
Python console, i.e. carries the result of calls to ``print(...,
file=sys.stderr)``. A variety of line-specific settings ensure that this is
done with as little overhead as possible.

If the link is lossless (e.g. the MCU emulates a serial port on USB, or
the link uses TCP), MsgPack or CBOR are run on the link as-is. Otherwise
the SerialPacker protocol is used to protect packet integrity; on top of
that, the ``Reliable`` module handles retransmissions.

The default is to use MsgPack without framing.

Some considerations:

* CBOR plus console data requires a lead-in or framing.

* A MsgPack link works without framing if the console data consists of
  ASCII only. Otherwise, i.e. if messages might contain UTF-8, it requires
  a lead-in or framing.

* A randomly unreliable line requires framing and loss protection.

* A deterministically unreliable link requires loss protection.

* ASCII console data on msgpack are transparent and don't require framing.

* Client/server TCP connections are one-shot and require no special
  handling.

* TCP links to a MCU that uses a network connection to "its" server typically
  tries to reconnect without losing state, and thus needs loss protection.

cbor
----

A flag. Set this if you want to use CBOR instead of MsgPack. The default is
`False`, but that might change.

If you use CBOR on a link that also carries stdout/stderr from the remote
system, you definitely need a lead-in or framing. With msgpack this is only
required if the output can contain UTF-8.

console
-------

A flag. If set, incoming console data (i.e. outside of a frame) will be
processed (e.g. printed to stderr). Further details are TODO.

Otherwise console data are ignored.

The default is `True` on serial lines, `False` for network links.

lossy
-----

Loss protection. If this element is missing or `None`, the link
is assumed to be lossless.

Otherwise this should be a map with these entries:

window
......

The maximum number of messages that have not been acknowledged. The
default is 8.

timeout
.......

Retransmission timer, in milliseconds. The default is 1000.

persist
.......

Mark the link as persistent: a link error will cause reconnecton
attempts.

If set and not `True`, the value is interpreted as the number of seconds 
until a failure is deemed to be permanent.

Loss protection 


frame
-----

SerialPacker configuration. If this element is missing or `None`, no
framing is performed.

Otherwise it should be a map with these entries:

idle
....

Inter-packet timeout im milliseconds. Default: 100.

max
...

Max packet length. The default is 127.

frame
.....

Frame start byte. The default is ``0x85``. `None` relies on inter-frame
timing and does not allow non-framed data.

This byte should not occur in standard console output. The frame receiver
understands UTF-8 sequences, thus the ranges ``0x00…0x1F``, and
``0x80…0xBF`` are safe to use.

mark
....

Every byte that's part of a frame *must* be prefixed with a ``mark``
byte. Other bytes are transmitted as-is. There is no provision for
escaping and no UTF-8 handling. A mark byte like "DLE" (0x10) should be
used that will not occur in normal console output.

This doubles the number of bytes transmitted. Don't use unless you need
to do really-low-level debugging.

Frame mark
----------

Alternately, ``frame`` can be an integer between ``0x00`` and ``0xFF``.
In this case, SerialPacker is not used; instead, the integer is used as
the packet lead-in byte. For maximum compatibility with console messages
this should be in the ``0x80…0xBF`` range.
