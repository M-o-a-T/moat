# command line interface
from __future__ import annotations

import datetime
import time
import anyio

import asyncclick as click
from moat.util import MsgReader, NotGiven, P, PathLongener, attr_args, yprint, Path, process_args
from moat.util.times import ts2iso, humandelta

from moat.link.client import Link
from moat.link._data import data_get, node_attr
from moat.link.meta import MsgMeta
from moat.link.node import Node


@click.command(short_help="Send a command")
@click.option("-S","--stream", is_flag=True, help="Read a stream")
@click.option("-R","--raw", is_flag=True, help="Show raw message data")
@click.argument("path", type=P, nargs=1)
@click.pass_context
@attr_args
async def cli(ctx, path, stream, raw, **kw):
    """
    Send a command to the server.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.port is not None:
        cfg.client.port = obj.port

    async with Link(cfg, name=obj.name) as conn:
        val = process_args(NotGiven, **kw)
        kw = {}
        if isinstance(val,list):
            args = val
        elif isinstance(val,dict):
            args = []
            for k,v in list(val.items()):
                if k.startswith("_"):
                    try:
                        kk = int(k[1:])
                    except ValueError:
                        pass
                    else:
                        if k>=len(args):
                            args += [NotGiven]*(k-len(args)+1)
                        args[k]=v
                        continue
                kw[k] = v
        elif val is NotGiven:
            args = []
        else:
            args = [val]

        if stream:
            async with conn.cmd(path, *args, **kw).stream_in() as res:
                yprint(rep_(res,raw), stream=obj.stdout)
                print("---", file=obj.stdout)
                async for msg in res:
                    yprint(rep_(msg,raw), stream=obj.stdout)
                    print("---", file=obj.stdout)
        else:
            res = await conn.cmd(path, *args, **kw)
        yprint(rep_(res,raw), stream=obj.stdout)


def rep_(res,raw=False):
    if raw:
        return res.args+[res.kw]
    if not res.args:
        return res.kw
    if res.kw:
        return res.args+[res.kw]
    if len(res.args) == 1:
        return res.args[0]
    return res.args
