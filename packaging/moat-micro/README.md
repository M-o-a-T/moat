# MoaT micro

% start synopsis

MoaT-Micro runs on top of MicroPython. It provides a rich set of building
blocks that can be connected with the MoaT-Cmd library, and several ways for
a server to connect to them. Controllers can be updated incrementally, and
their file system can be mounted on the server.

A compatibility library ensures that most of these blocks can also run on
CPython, thus simplifying debugging. MicroPython' REPL is available.

Like all of MoaT, the Python code is written in an async-first way.

% end synopsis


## Operation

Installing MoaT on a microcontroller is a one-stop process that involves
building a slightly modified version of MicroPython that includes the MoaT
library.

NVRAM (if present) or a status file control whether / how to start the
system. The main code loads a config file that specifies the application
code blocks to run and the communication channels to open and/or listen on.


## Supported devices

Basically anything that can run MicroPython and has enough flash (2MB) and
RAM (128k).

This does include the ESP8266, if barely.

## Principle of Operation

Each controller runs a main task which loads some applications. These apps
might do something locally, e.g. let a LED blink or poll a button, provide
a link to a remote system, or call other apps for high-level functions.

Apps can be connected to each other freely, via the standard MoaT-Link mechanism.
These links are designed to be transparent: server code may freely call
code on a satellite, or vice versa.

All app-related code is written in async Python. We use ``anyio`` on the
multiplexer and native asyncio on the MCUs; a shallow compatibility layer
ensures that most code can be shared. Blocking operations are delegated to
a separate thread if the controller supports them.


## Installation

```shell
pip install moat-micro
moat -c your-config.cfg micro setup -i
```

The interesting part is of course how to write the configuratio file.

For details see the config file documentation, section [Installation](config.md#install-top).

A simple tutorial is [here](tutorial.md).


### MicroPython

Our fork of MicroPython is kept up-to-date with the official release. It
contains a couple of improvements, all of which are separate branches in
the [MoaT repository](https://github.com/M-o-a-T/micropython):

* dupterm: the Unix version of MPy always prints the dup'd output to the
  terminal. MoaT can't work that way.

* namespace-update: MPy traditionally searched subpackages only in the path
  where their top-level name is found. That doesn't work when you want to
  upload small bugfixes to a large codebase.

* moat\_build: Building with nonstandard build directories tends to leak
  that build directory to `mpy-cross`. That doesn't work.

* moat\_lib: MoaT includes a few improvement to the MPy library.

* async-extend: asyncio's way of writing to and closing a stream is a
  historical relict. We can do better.

* unix\_embed: Teach the unix version of MicroPython to behave exactly like
  its embedded counterpart, i.e. read `boot.py` and `main.py`, understand
  raw mode, and all that.

* hash\_frozen: Add hash values for all modules embedded in the MicroPython
  binary. That way we can check whether they should be replaced with an
  update in the ROM image or the file system.

* taskgroup: Taskgroups are essential for structuring large async
  applications and ensuring that exceptions do not get lost (or leave
  disconnected threads behind).

* thread: We add minimal threading support to asyncio.


## Included Apps

The following list is incomplete because we can't think of everything
(and don't own the hardware you do). Fortunately, writing additional
building blocks is reasonably easy.

### Hardware

* I²C
* Analog input
* Analog output
* Digital I/O
* UART (serial)

### Drivers

* Temperature sensors
* Humidity sensors
* PWM modulator
* PID controller.
* Relay controller (digital output with manual override)
* Hardware or software watchdog
* NVRAM and RTC

### Data

* Transfer (e.g.: read analog input, send to PID, send that to PWM output …)
* Calculate a moving average
* TODO: threshold with hysteresis

### Communication

* TCP links (incoming, outgoing, server).
* Serial, with error recovery
* USB
* TODO: encryption and authorization

### Internals

* System control: Python `eval`, free memory, reboot, …
* Configuration updates
* File system access
* MicroPython's [REPL](repl.md)
* TODO: ROM file system update
* MoaT-CMD built-ins (directory, documentation)


### File system access

The LittteFS file system on the client is accessible across the link when
the `fs` module is loaded. It can also be mounted on the server.

If you write to the client, be aware that some programs do not buffer their
data; writing in single bytes does take a long(ish) time. Most notably, this
applies to `mpy-cross`.
