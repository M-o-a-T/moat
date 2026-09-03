#!/usr/bin/python3
"implements a bus server for our fake bus"

from __future__ import annotations

import sys
from subprocess import PIPE

import asyncclick as click
import trio

from moat.bus.backend._stream import StreamHandler
from moat.bus.server import Server


@click.command()
async def main() -> None:  # noqa:D103
    try:
        proc = await trio.lowlevel.open_process(
            ["bin/fake_serialbus"],
            stdin=PIPE,
            stdout=PIPE,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        backstream = trio.StapledStream(proc.stdin, proc.stdout)

        async with StreamHandler(None, backstream) as sb, Server(sb) as m:  # ty:ignore[invalid-argument-type]
            async for _evt in m:
                print(m)
    except trio.ClosedResourceError:
        print("Closed.", file=sys.stderr)


if __name__ == "__main__":
    main()
