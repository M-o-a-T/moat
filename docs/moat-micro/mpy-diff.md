# Differences to official MicroPython

Unfortunately, MoaT support requires a few changes to the official
MicroPython distribution.

Installing MoaT-Micro with unmodified MicroPython is currently not
supported. (Also, it won't work.)

## Importing

MicroPython supports `sys.path`; unfortunately it forces all packages of a
namespace to be imported from the same directory.

MoaT supports selectively updating individual files. Being forced to update
the whole of `lib/moat/*` because of a typo somewhere would cause many
satellites to run out of RAM. (It's also slow.)

## Hashing

The code in `.frozen` cannot be read. We add a frozen "_hash" module that
contains a path-to-digest mapping so our updater can figure out which
modules to not update (or even delete from the file system, when you revert
a change that doesn't work, or a debug command).

## Taskgroups

We include a subset of `asyncio.TaskGroup`.
This also adds minimal support for `BaseExceptionGroup` and `ExceptionGroup`.

## Threading

We include a subset of `asyncio.threads.to_thread`.

## asyncio: write+drain

CPython's historic write-plus-async-drain method of writing to an async
stream requires a superfluous function call and a buffer copy. We add an
`awrite` method.

## Sleep handling bugfix

Stock MicroPython has a bug where two tasks that start sleeping at the
exact same time step onto each other.

## Task hashing

Stock MicroPython doesn't let us task objects as dictionary keys.

## Exception handling

There's an obscure bug (or at least an unhandled condition) in `py/vm.c`
which needs tracking down.

## dupterm

The Unix port of MicroPython doesn't enable `os.dupterm`, which prevents us
from testing that feature.

## Building

### mpy-cross

Building with a separate build directory frequently causes mpy-cross to end
up in a separate build directory too. This causes assembling frozen modules
to fail.

### esp32: idf.py

Allow specifying the `idf.py` name and/or its path.

## esp8266: baud rate

The boot baud rate for ESP8266 is 74880 baud. Use that rate for MicroPython
so that a reboot doesn't end up spewing nonsense to the console.

## rp2: allocate romfs space

We allocate 200 kBytes of ROM file system by default.

## Unix: Enable raw mode via command line

For automated testing it's very useful to start off in raw mode, and to
auto-run `boot.py` and `main.py`.

## default to enabling `sys.settrace`

Sometimes you do need to run a debugger on the satellite.

## Decoding half-floats

The decoder for 16-bit floats was not exported.
