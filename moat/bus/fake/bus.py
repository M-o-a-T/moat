#!/usr/bin/python3

"""
This is a simulated MoaT bus. It offers a Unix socket.

*** This bus simulation is active high ***

"""

from __future__ import annotations

import anyio
import os
import time
from contextlib import asynccontextmanager, suppress
from random import random

import asyncclick as click

_seq = 0


class Main:  # noqa:D101
    def __init__(self, **kw):
        self.clients = set()
        self.trigger = anyio.create_event()
        for k, v in kw.items():
            setattr(self, k, v)
        self.t = None

    def trigger_update(self):  # noqa:D102
        self.trigger.set()

    def add(self, client):  # noqa:D102
        client.last_b = b""
        self.clients.add(client)
        if self.verbose:
            print("+++")

        self.trigger_update()

    def remove(self, client):  # noqa:D102
        try:
            self.clients.remove(client)
        except KeyError:
            pass
        else:
            if self.verbose:
                print("---")

            self.trigger_update()
            if not self.clients:
                self.t = None

    def report(self, n, val):  # noqa:D102
        if not self.verbose:
            return
        t = time.monotonic()
        self.t, t = t, (0 if self.t is None else t - self.t)

        n = f"{n:%02d}" if n else "--"

        print(f"{t:6.3f} {n} {val:02x}")

    async def run(self):  # noqa:D102
        last = -1
        val = 0
        while True:
            if last != val:
                await anyio.sleep((random() * self.max_delay + self.delay) / 1000)
            else:
                await self.trigger.wait()
            if self.trigger.is_set():
                self.trigger = anyio.create_event()

            val = 0
            for c in self.clients:
                if c.data is not None:
                    val |= c.data

            self.report(0, val)
            b = bytes((val,))
            for c in list(self.clients):
                if c.last_b == b:
                    continue
                c.last_b = b
                try:
                    await c.send(b)
                except (OSError, BrokenPipeError, anyio.BrokenResourceError):
                    self.remove(c)

            last = val

    async def serve(self, client):  # noqa:D102
        global _seq
        _seq += 1
        n = _seq

        client.data = None
        self.add(client)
        try:
            async with client:
                while True:
                    try:
                        data = await client.receive(1)
                    except (
                        anyio.EndOfStream,
                        ConnectionResetError,
                        anyio.BrokenResourceError,
                        anyio.ClosedResourceError,
                    ):
                        data = None
                    if not data:
                        return
                    client.data = data[0]
                    if self.verbose:
                        self.report(n, client.data)
                    self.trigger_update()
        finally:
            self.remove(client)


@asynccontextmanager
async def mainloop(tg, **kw):  # noqa:D103
    mc = Main(**kw)
    await tg.spawn(mc.run)
    yield mc


@click.command()
@click.option("-s", "--socket", "sockname", help="Socket to use", default="/run/moatbus")
@click.option("-v", "--verbose", help="Report changes", is_flag=True)
@click.option("-d", "--delay", type=int, help="fixed delay (msec)", default=0)
@click.option("-D", "--max-delay", type=int, help="random delay (msec)", default=0)
async def main(sockname, **kw):  # noqa:D103
    with suppress(OSError):
        os.unlink(sockname)

    listener = await anyio.create_unix_listener(sockname)
    async with listener, anyio.create_task_group() as tg, mainloop(tg, **kw) as loop:
        await listener.serve(loop.serve)


if __name__ == "__main__":
    main(_anyio_backend="trio")
