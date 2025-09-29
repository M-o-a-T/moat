#!/usr/bin/python3
"# noqa:D100"

from __future__ import annotations

import socket

import asyncclick as click
import trio


async def reader(sock, verbose):  # noqa:D103
    while True:
        b = await sock.recv(1)
        if not b:
            return
        if verbose:
            print("IN ", b[0])


@click.command(
    help="""
Periodically set some wires on the fake bus.

The initial state is zero, i.e. all bits clear, but you can use '--init' to
change that.

Arguments show which bit (or bits, separate with comma) to flip at each
step. Bits are numbered starting with 1, a zero is a no-op.

The sequence repeats until `--loops`, if used, or interrupted.
""",
)
@click.option("-s", "--socket", "sockname", help="Socket to use", default="/tmp/moatbus")  # noqa:S108
@click.option("-d", "--delay", type=float, default=0.1, help="Delay(sec) until next flip")
@click.option("-v", "--verbose", is_flag=True, help="Be verbose")
@click.option("-i", "--init", type=int, default=0, help="Initial wire state")
@click.option("-n", "--loops", type=int, default=-1, help="Stop after this many iterations")
@click.argument("data", nargs=-1)
async def run(sockname, delay, verbose, data, init, loops):  # noqa:D103
    if not data:
        if not init:
            raise click.UsageError("Need some data")
        delay = 99999
        data = ["0"]

    with trio.socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        await sock.connect(sockname)
        async with trio.open_nursery() as n:
            n.start_soon(reader, sock, verbose)

            s = init
            if s:
                await sock.send(bytes((s,)))
                await trio.sleep(delay)
            while loops:
                loops -= 1
                for x in data:
                    for b in (int(d) for d in x.split(",")):
                        if b:
                            s = s ^ (1 << (b - 1))
                    if verbose:
                        print("OUT", s)
                    await sock.send(bytes((s,)))
                    await trio.sleep(delay)


if __name__ == "__main__":
    run()
