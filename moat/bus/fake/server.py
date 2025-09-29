#!/usr/bin/python3
"implements a bus server for our fake bus"

from __future__ import annotations

import sys
from subprocess import PIPE

import asyncclick as click
import trio
from moatbus.backend.stream import StreamBusHandler
from moatbus.server import Server


@click.command()
async def main():  # noqa:D103
    try:
        async with await trio.open_process(
            ["bin/fake_serialbus"],
            stdin=PIPE,
            stdout=PIPE,
        ) as backend:
            backstream = trio.StapledStream(backend.stdin, backend.stdout)

            async with StreamBusHandler(backstream) as sb, Server(sb) as m:
                async for _evt in m:
                    print(m)
    except trio.ClosedResourceError:
        print("Closed.", file=sys.stderr)


if __name__ == "__main__":
    main()
