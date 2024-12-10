#!/usr/bin/python3

import asyncclick as click
from fakebus.client import Client
from moatbus.message import BusMessage
from moatbus.handler import RES

@click.command()
@click.option("-s","--socket", help="Socket to use",default="/tmp/moatbus")
@click.option("-b","--bits", help="Number of bits",default=3)
@click.option("-t","--timeout", type=float,help="Timer A in msec",default=10)
@click.option("-T","--timerB", type=float,help="Timer B in msec",default=5)
@click.option("-S","--source", help="Source addr",default=1)
@click.option("-D","--dest", help="Destination addr",default=2)
@click.option("-C","--cmd", help="Command",default=0)
@click.option("-v","--verbose", is_flag=True, help="Be verbose")
@click.argument("data", nargs=-1)
async def run(socket,timeout,timerb, source,dest,cmd, data,bits,verbose):
    async with Client(wires=bits,socket=socket,timeout=timeout,timeout2=timerb,verbose=verbose).run() as client:
        msg = BusMessage()
        msg.src = source
        msg.dst = dest
        msg.code = cmd
        data = ' '.join(data).encode("utf-8")
        msg.start_send()
        msg.add_data(data)

        await client.send(dest,msg)
        print(msg.res)


if __name__ == "__main__":
    run()
