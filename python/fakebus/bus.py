#!/usr/bin/python3

"""
This is a simulated MoaT bus. It offers a Unix socket.

*** This bus simulation is active high ***

"""
import anyio
import socket
import asyncclick as click
from contextlib import asynccontextmanager
import time
import os
from random import random
from functools import partial

_seq = 0

class Main:
    def __init__(self, **kw):
        self.clients = set()
        self.trigger = anyio.create_event()
        for k,v in kw.items():
            setattr(self,k,v)
        self.t = None

    async def trigger_update(self):
        self.trigger.set()

    async def add(self, client):
        client.last_b = b''
        self.clients.add(client)
        await self.trigger_update()

    async def remove(self, client):
        try:
            self.clients.remove(client)
        except KeyError:
            pass
        else:
            await self.trigger_update()
            if not self.clients:
                self.t = None

    def report(self, n, val):
        if not self.verbose:
            return
        t = time.monotonic()
        self.t,t = t,(0 if self.t is None else t-self.t)

        n = "%02d"%n if n else "--"

        print("%6.3f %s %02x" % (t,n,val))

    async def run(self):
        last = -1
        val = 0
        while True:
            if last != val:
                await anyio.sleep((random()*self.max_delay+self.delay)/1000)
            else:
                await self.trigger.wait()
            if self.trigger.is_set():
                self.trigger = anyio.create_event()

            self.report(0,val)
            b = bytes((val,))
            for c in list(self.clients):
                if c.last_b == b:
                    continue
                c.last_b = b
                try:
                    await c.send(b)
                except (BrokenPipeError,EnvironmentError,anyio.BrokenResourceError):
                    await self.remove(c)

            last = val
            val = 0
            for c in self.clients:
                if c.data is not None:
                    val |= c.data

    async def serve(self, client):
        global _seq
        _seq += 1
        n = _seq

        client.data = None
        await self.add(client)
        await self.trigger_update()
        try:
            async with client:
                while True:
                    try:
                        data = await client.receive(1)
                    except (anyio.EndOfStream,ConnectionResetError,anyio.BrokenResourceError,anyio.ClosedResourceError):
                        data = None
                    if not data:
                        return
                    client.data = data[0]
                    if self.verbose:
                        self.report(n,client.data)
                    await self.trigger_update()
        finally:
            await self.remove(client)


@asynccontextmanager
async def mainloop(tg,**kw):
    mc = Main(**kw)
    await tg.spawn(mc.run)
    yield mc

@click.command()
@click.option("-s","--socket","sockname", help="Socket to use",default="/tmp/moatbus")
@click.option("-v","--verbose", help="Report changes",is_flag=True)
@click.option("-d","--delay", type=int,help="fixed delay (msec)",default=0)
@click.option("-D","--max-delay", type=int,help="random delay (msec)",default=0)
async def main(sockname, **kw):
    try:
        os.unlink(sockname)
    except EnvironmentError:
        pass

    listener = await anyio.create_unix_listener(sockname)
    async with listener, anyio.create_task_group() as tg, \
                mainloop(tg, **kw) as loop:
        await listener.serve(loop.serve)

if __name__ == "__main__":
    click.anyio_backend="trio"
    main()

