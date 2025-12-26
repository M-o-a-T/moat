#!/usr/bin/python3  # noqa:D100

from __future__ import annotations

import anyio
import datetime
import sys
import time

import asyncclick as click
import httpx
from asyncakumuli import get_data

from moat.util import CFG, P
from moat.link.client import Link
from moat.run import main_, run

series = "price"
tags = dict(type="power", source="awattar", redo="A")


def sdate(d):  # noqa: D103
    d = datetime.datetime.fromtimestamp(d)  # noqa:DTZ006
    return d.strftime("%Y-%m-%d %H:%M")


async def empty(ctx):  # noqa: D103
    pass


@main_.command()
@click.option("--path", "-p", type=P, help="Value to set")
@click.option("--verbose", "-v", is_flag=True, help="Report values as set")
@click.option("--offset", "-o", type=float, help="offset from start (seconds)", default=0)
async def back(path, verbose, offset):
    """
    Feed a stored Akumuli time series back to MoaT-KV.
    """
    if path is None and not verbose:
        raise click.UsageError("No path and no verbosity is a no-op")
    tt = time.time()
    val = None
    async with Link(CFG.moat.link) as cli, httpx.AsyncClient() as s:
        while True:
            seen = False
            t = datetime.datetime.now()  # noqa:DTZ005
            async for v in get_data(
                s,
                series,
                tags,
                url="http://a.rock.s:50081/api/query",
                t_start=t - datetime.timedelta(0, 10000 - offset),
                t_end=t + datetime.timedelta(2, offset),
            ):
                if v.time + offset < tt:
                    print("Skip:", v.time)
                    val = v.value
                    continue
                if val is not None:
                    if verbose:
                        print(val)
                        sys.stdout.flush()
                    if path is not None:
                        await cli.d_set(path, val, retain=True)
                elif verbose:
                    print("Series starts in the future", file=sys.stderr)
                print("Sleep:", v.time + offset - tt, "to", sdate(v.time + offset))
                await anyio.sleep(v.time + offset - tt)
                tt = time.time()
                val = v.value
                seen = True
            if not seen:
                print("No data, sleeping", file=sys.stderr)
                await anyio.sleep(3000)


run(empty)
