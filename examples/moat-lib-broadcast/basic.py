#!/usr/bin/env python3
"""
Basic example of using the Broadcaster class from moat.lib.broadcast
"""

from __future__ import annotations

import anyio

from moat.lib.broadcast import Broadcaster


async def reader(bc, name):  # noqa:D103
    async for msg in bc:
        print(f"{name} received: {msg}")


async def main():  # noqa:D103
    async with anyio.create_task_group() as tg, Broadcaster() as bc:
        # Start readers
        tg.start_soon(reader, aiter(bc), "Reader1")
        tg.start_soon(reader, bc.reader(10), "Reader2")  # explicit queue length

        # Give readers time to start
        await anyio.sleep(0.1)

        # Send messages
        bc("Hello")
        await anyio.sleep(0.1)
        bc("World")


if __name__ == "__main__":
    anyio.run(main)
