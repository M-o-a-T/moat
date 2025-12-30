#!/usr/bin/python3
"""Test script for moat.lib.repl multiline input."""

from __future__ import annotations

import anyio
import sys
from contextlib import AsyncExitStack

from moat.util import Path
from moat.lib.repl import ReadlineAlikeReader as Reader
from moat.lib.repl import multiline_input


async def main_old():
    """Test multiline input functionality."""
    # inp = await input("=== ")
    inp = await multiline_input(lambda r: "\n" not in r, "=== ", "--- ")
    print("RES:", repr(inp))


async def main(mode):
    """Test multiline input functionality."""
    match mode:
        case 1:
            inp = await multiline_input(lambda r: "\n" not in r, "=== ", "--- ")
        case 2 | 3:
            # inp = await input("=== ")
            from moat.lib.repl import UnixConsole  # noqa:PLC0415

            async with AsyncExitStack() as acm:
                console = await acm.enter_async_context(UnixConsole())
                if mode == 3:
                    from moat.lib.repl import MsgConsole  # noqa:PLC0415
                    from moat.lib.rpc import MsgSender  # noqa:PLC0415

                    msg_handler = MsgConsole(console)
                    console = MsgSender(msg_handler).sub_at(Path())
                    console = await acm.enter_async_context(console)

                r = await acm.enter_async_context(Reader(console=console))
                r.more_lines = lambda r: "\n" not in r
                r.ps1 = r.ps2 = "=== "
                r.ps3 = r.ps4 = "--- "
                inp = await r.readline()
    print("RES:", repr(inp))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} 1/2/3")
        sys.exit(1)
    anyio.run(main, int(sys.argv[1]))
