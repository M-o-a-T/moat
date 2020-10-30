#!/usr/bin/python3

import anyio
import asyncclick as click
from fakebus.client import Client
from moatbus.message import BusMessage
from moatbus.handler import RES

async def reader(sock, verbose):
    while True:
        b = await sock.receive(1)
        if verbose:
            print("IN ",b[0])
@click.command(help="""
Periodically set some wires on the fake bus.

The initial state is zero, i.e. all bits clear, but you can use '--init' to
change that.

Arguments show which bit (or bits, separate with comma) to flip at each
step. Bits are numbered starting with 1, a zero is a no-op.

The sequence repeats until `--loops`, if used, or interrupted.
""")
@click.option("-s","--socket", help="Socket to use",default="/tmp/moatbus")
@click.option("-d","--delay", type=float,default=0.1, help="Delay(sec) until next flip")
@click.option("-v","--verbose", is_flag=True, help="Be verbose")
@click.option("-i","--init", type=int, default=0, help="Initial wire state")
@click.option("-n","--loops", type=int, default=-1, help="Stop after this many iterations")
@click.argument("data", nargs=-1)
async def run(socket,delay,verbose,data,init,loops):
    if not data:
        if not init:
            raise click.SyntaxError("Need some data")
        delay=99999
        data = ["0"]
    async with await anyio.connect_unix(socket) as sock, anyio.create_task_group() as tg:
        await tg.spawn(reader, sock, verbose)
        s = init
        if s:
            await sock.send(bytes((s,)))
            await anyio.sleep(delay)
        while loops:
            loops -= 1
            for x in data:
                for b in (int(d) for d in x.split(',')):
                    if b:
                        s = s ^ (1<<(b-1))
                if verbose:
                    print("OUT",s)
                await sock.send(bytes((s,)))
                await anyio.sleep(delay)

if __name__ == "__main__":
    run()
