#!/usr/bin/python3

import anyio
import asyncclick as click
from fakebus.client import Client

@click.command()
@click.option("-s","--socket", help="Socket to use",default="/tmp/moatbus")
@click.option("-b","--bits", help="Number of bits",default=3)
@click.option("-t","--timeout", type=float,help="Timer A in msec",default=10)
@click.option("-T","--timerB", type=float,help="Timer B in msec",default=5)
@click.option("-v","--verbose", is_flag=True, help="Be verbose")
@click.option("-D","--dest", type=int, help="Destination addr",default=None)
async def run(socket,timeout,timerb,bits,dest,verbose):
    async with Client(wires=bits,socket=socket,dest=dest,timeout=timeout,timeout2=timerb,verbose=verbose).run() as client:
        async for msg in client:
            print(msg)

if __name__ == "__main__":
    run()
