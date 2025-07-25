"""
Command line for gatewaying
"""
from __future__ import annotations

import datetime
import time
import anyio

import asyncclick as click
from moat.util import MsgReader, NotGiven, P, PathLongener, attr_args, yprint, Path
from moat.util.times import ts2iso, humandelta

from moat.link.client import Link
from moat.link._data import data_get, node_attr
from moat.link.meta import MsgMeta
from moat.link.node import Node


@click.group(short_help="Manage gateways.", invoke_without_command=True)
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path):
    """
    This subcommand gates MoaT-Link data to/from other channels.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.port is not None:
        cfg.client.port = obj.port
    obj.conn = await ctx.with_async_resource(Link(cfg, name=obj.name))
    obj.path = path
    if ctx.invoked_subcommand is None:
        await _list(obj)


@cli.command()
@click.pass_obj
async def run(obj):
    """
    Run a gateway setup.
    """
    from moat.link.gate import run_gate
    from moat.util.systemd import as_service
    async with as_service(obj) as srv:
        await srv.tg.start(run_gate, obj.cfg, obj.conn, P("gate")+obj.path)
        srv.set()
        await anyio.sleep_forever()


@cli.command("list")
@click.pass_obj
async def list_(obj):
    """
    List gates / a gate's data.
    """
    await _list(obj)

async def _list(obj):
    if not obj.path:
        seen = False
        async with obj.conn.d_walk(P("gate"),min_depth=1,max_depth=1) as mon:
            async for p,d in mon:
                seen = True
                print(p[-1])
        if not seen and obj.debug:
            print("- no data.", file=sys.stderr)
        return

    k = {}
    k["recursive"] = True
    k["raw"] = True
    k["empty"] = True
    await data_get(obj.conn, P("gate")+obj.path, **k)


@cli.command("set", short_help="Add or update a gate entry")
@attr_args
@click.option("-S", "--src", type=P, help="Source (in Moat-Link)")
@click.option("-D", "--dst", type=P, help="Destination (driver specific)")
@click.option("-d", "--driver", type=str, help="Driver")
@click.pass_obj
async def set_(obj, src,dst,driver, **kw):
    """
    Add/change a gateway entry.
    """

    if not len(obj.path):
        raise SyntaxError("Can't set the top level")
    if driver:
        kw["vars_"] += ((P("driver"), driver),)
    if src:
        kw["path_"] += ((P("src"), src),)
    if dst:
        kw["path_"] += ((P("dst"), dst),)
    res = await node_attr(obj, P("gate")+obj.path, **kw)


class nstr:
    def __new__(cls, val):
        if val is NotGiven:
            return val
        return str(val)


@cli.command(short_help="Delete an entry / subtree")
@click.option(
    "-b",
    "--before",
    type=float,
    help="Don't delete entries created after this timestamp",
)
@click.option("-r", "--recursive", is_flag=True, help="Delete a complete subtree")
@click.pass_obj
async def delete(obj, before, recursive):
    """
    Delete an entry, or a subtree.

    You really should use "--before" flag to ensure that no other change
    arrived after you viewed the data in question.

    Non-recursively deleting an entry with children works and does *not*
    affect the child entries.

    The root entry cannot be deleted.
    """
    args = {}
    if recursive:
        args["rec"]=recursive
    if before:
        args["ts"]=before
    res = await obj.conn.d.delete(obj.path, **args)
    if obj.meta:
        res=dict(data=res[0],meta=MsgMeta.restore(res[1:]).repr())
    else:
        res = res[0]
    yprint(res, stream=obj.stdout)

