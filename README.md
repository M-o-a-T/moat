# MoaT micro

This module contains code to talk to MoaT satellites running MicroPython.

## Operation

After installation, the MicroPython node runs a script that loads a config
file, set up networking if possible, and then accepts structured commands
across TCP or a serial link.

## Supported devices

Basically, anything that can run MicroPython and has barely enough RAM.

This does include the ESP8266, though you need to compile the MoaT support
code directly into Flash.

## Installation

### MicroPython

`moat.micro` comes with its own MicroPython fork, for two reasons.

One is that async code on MicroPython is not yet supported natively, as of
2023-02-26.

The other is that most µPy systems don't have enough RAM to load the MoaT
code. It hasn't been size-optimized (much). While that too will change,
some devices (in particular, the ESP8266) just don't have enough RAM.

For these reasons, you need to build and flash a MicroPython image that
includes a "frozen" copy of the embedded MoaT modules. (You can still
upload your own enhancements.)

Go to `lib/micropython/ports/esp32` (or whichever microcontroller you have).
Add this line to `boards/manifest.py`:

	include("../../../../../moat/micro/_embed/lib")

You might have to modify the number of `../` prefixes based on the build
system of the port in question.

Run `make` and flash your board as appropriate. Connect to it, and verify
that you get a MicroPython prompt.

#### Serial link

Copy `configs/fallback_serial.cfg` to `whatever.cfg` and edit as appropriate.

Run this command:

	moat micro -c whatever.cfg setup \
		-C micro/lib/micropython/mpy-cross/build/mpy-cross \
		-c whatever.cfg -s micro/moat/micro/_embed/main.py \
		-S std -m

initally, or

	moat micro -c whatever.cfg mplex

afterwards.


#### Networking

Copy `configs/fallback_net.cfg` to `whatever.cfg` and edit as appropriate.

Run these commands:

	moat micro -c whatever.cfg setup \
		-C micro/lib/micropython/mpy-cross/build/mpy-cross \
		-c whatever.cfg -s micro/moat/micro/_embed/main.py \
		-S std

once, then

	moat micro -c whatever.cfg mplex -r

to talk to the satellite.

## Commands

There's a basic directory function:

	moat micro -c whatever.cfg cmd _dir

* c

  A list of commands you can call directly.

* d

  A list of submodules. You can enumerate them, too:

	moat micro -c whatever.cfg cmd sys._dir

Online docstrings for these are on the TODO list.

### Built-in commands

#### ping

Your basic "are you still there?" message. Echoes its `m` argument. Not for
machine consumption.

#### sys.is\_up

Triggers sending a "link" message.

## Message structure

Messages are encoded using MsgPack dictionaries. Short keywords are used to
conserve client memory.

* a

  Command Action. May be either a string or a list of strings.

  If this field is missing, the message is a reply.

* d

  Data. Commands use a dict: keyword args to the command in question.
  Replies use whatever data the command returns.

* i

  Sequence number. An action with a sequence number *must* be replied to,
  eventually. Actions without sequence numbers are unsolicited typed status
  messages. Replies without sequence numbers are illegal.

* e

  Error. The content is a string (error type), data must be an array
  (arguments).

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

