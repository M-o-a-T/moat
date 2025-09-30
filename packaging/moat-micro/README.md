# MoaT micro

This module contains code to talk to MoaT satellites running MicroPython.

## Operation

After installation, the MicroPython node runs a script that loads a config
file, connects to a microcontroller (or two or …), runs some application
code, and accepts structured commands across TCP or Unix sockets.

There is no conceptual difference between the master program and the
microcontrollers; if the MCU supports networking, you can connect MCUs
directly to each other.

## Supported devices

On servers, CPython or (possibly) PyPy.

On satellites, basically anything that can run MicroPython and has enough
flash (2MB) and RAM (128k).

This does include the ESP8266, if barely.

On most MCUs there is not enough RAM to load the MoaT support code.
Thus, you need to build a version of MicroPython that includes the MoaT
modules in Flash. The installer script uses MoaT's MicroPython fork
to build the required binaries.

## Principle of Operation

Each controller runs a main task which loads some applications. These apps
might do something locally, e.g. let a LED blink or poll a button, provide
a link to a remote system, or call other apps for high-level functions.

Apps are connected hierarchically. They can send messages to each other;
a message may return a reply ("read this temperature").

Multiple replies ("read this temperature every ten seconds") are supported.

All app-related code is written in async Python. We use ``anyio`` on the
multiplexer and native asyncio on the MCUs; a shallow compatibility layer
ensures that most code can be shared.


## Installation

See "INSTALL".

### MicroPython

Our fork of MicroPython is kept up-to-date with the official release. It
contains a couple of improvements:

* Taskgroups are essential for structuring large async applications. Our
  version includes support for them.

* Our version does not require submodules to be located below the same path
  as their parent modules.

* We include a ``_hash`` module, which contains a mapping of hashes for the
  source code of the modules included in Flash.

The latter two changes allow you to selectively update single packages, while
the rest of the system continues to run from code "frozen" into flash. This
saves on RAM usage and/or Flash cycles, particularly when debugging.


## MoaT.micro Commands

### Built-in commands

#### command directory lookup

There's a directory function:

	moat micro -c whatever.cfg cmd dir

* c

  A list of commands you can call directly.

* d

  A list of submodules. You can enumerate them:

	moat micro -c whatever.cfg cmd sys.dir

Online docstrings are on the TODO list.


#### ping

Your basic "are you still there?" message. Echoes its `m` argument. Not for
machine consumption.

#### sys.is\_up

Triggers sending a "link" message.

## Message structure

See `doc/messages.md`.

### Built-in unsolicited messages

#### link

Send when a link is established (data: ``True``) or taken down (data:
``False``).

Obviously you cannot depend on any of these to happen automatically. Use
`sys.is_up` to trigger this message if you don't get it after connecting;
use .

### Proxy objects

Objects which cannot be encoded to MsgPack are sent as Proxy objects (MsgPack
extension 4, content: proxy name). The name is opaque. Proxies are cached
on the side which generates them; the recipient is responsible for
calling `sys.unproxy(proxy_obj)` to release them.

`Proxy('-')` is a special "no data" object, used e.g. for deleting config
options.


## Supported links

Either serial console or TCP works.

### TCP

The default is port 27587. We directly send MsgPack messages; they're
self-terminating, thus no length bytes or related silliness is required.

### Serial data

Serial data come in two flavors, either lossy (your basic UART signal) or
lossless (the microcontroller emulates a serial interface over USB).

In the first case we use the `SerialPacker` module, with a start byte,
to transmit single MsgPack messages. (Anything not introduced with the
start byte is console output.) On top of this we add basic recovery.

For the second case we can use a MsgPack data stream directly. As MsgPack
encodes integers (0…127) as single bytes, we also can interleave console
output with our messages.

## Shared link

The connection to the microcontroller is a 1:1 link. (This is obvious when
using serial data, but using just one TCP connection also conserves
controller memory.)

In order to support multiple parallel usages, a simple multiplexing
protocol allows clients to connect using a Unix-domain socket.

## Configuration

Configuration data for a module is stored on the module. You can read and
update it online, though reading of larger config files is best done via
the file system.

### wdt

Watchdog timer configuration.

* t

  Timeout. You need to send a ``sys.wdt`` message every this-many seconds.
  The default is 10 seconds.

* s

  Start. 0: manually, 1: immediately, 2: after network config, 3:
  before task start, 4: before mainloop start. The default is zero.

  Note that each of these phases might take multiple seconds.

* n

  If you autostart the watchdog, the first ``n`` watchdog periods are covered by
  the controller. After that, you need to have established a connection and
  started sending periodic ``sys.wdt`` messages.

  n=-1: no "free" watchdog messages. The default is ``3``, but at least one
  minute.

  The first ``sys.wdt`` message terminates the effect of this parameter.


## Modular applications

As controllers have different functions, it's possible – and in fact quite
simple – to send specialized applications to it.

Applications are activated using a configuration file which can be updated
remotely.

Modules can use all resources on the controller but should be careful not
to use blocking code if possible.

In order to support long-running applications and complex operations for which
the controller isn't suited, application modules can also run on the muktiplexer.

### File system access

The LittteFS file system on the client is accessible across the link when
the `fs` module is loaded. It can also be mounted on the server.

If you write to the client, be aware that some programs do not buffer their
data; writing in single bytes does take a long(ish) time. Most notably, this
applies to `mpy-cross`.
