# Architecture — moat.lib.repl

Interactive async REPL / console: line editor, history, completion,
terminfo, keymaps, pager, and Unix/Windows console backends.

## Files (`repl/*.py`, ~26 files)

A full-featured interactive console subsystem: input editing with cursor
movement, multi-line input, history recall, tab completion, terminfo-driven
key sequences, configurable keymaps, and a pager. Console backends cover Unix
terminals and Windows.

## Consumers

Drives the MicroPython host-side interactive console (the `moat micro`
interactive session), the device-side `moat.micro.console` (mirrored subset
under `moat/micro/_embed/lib/moat/micro/console.py`), and any MoaT command
needing a rich interactive prompt over an async stream. Out-of-band console
channels `cwr`/`crd` on `moat.lib.stream` carry this REPL alongside data.
