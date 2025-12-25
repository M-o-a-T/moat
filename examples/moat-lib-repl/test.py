#!/usr/bin/python3
from __future__ import annotations

import anyio

from moat.lib.repl.readline import multiline_input


async def main():
    # inp = await input("=== ")
    inp = await multiline_input(lambda r: "\n" not in r, "=== ", "--- ")
    print("RES:", repr(inp))


if __name__ == "__main__":
    anyio.run(main)
