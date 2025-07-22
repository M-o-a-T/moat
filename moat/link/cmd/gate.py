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
    This subcommand accesses the data stored in the MoaT-Link server.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.port is not None:
        cfg.client.port = obj.port
    obj.conn = await ctx.with_async_resource(Link(cfg))
    if ctx.invoked_subcommand is None:
        res = await data_get(obj.conn, path, recursive=False)
    else:
        obj.path = path


@cli.command()
@click.argument("name", type=str)
async def run(obj,name):
    """
    Run a gateway setup.
    """
    res = await obj.conn.d.get(P("gate")/name)
    gate = get_gate(obj.cfg, res)
    await gate.run(obj.cfg)



@cli.command("list")
@click.argument("name",nargs=-1)
@click.pass_obj
async def list_(obj, name:list[str]):
    """
    List gates / a gate's data.
    """

    if not name:
        seen = False
        async with obj.conn.d_walk(P(":R.gate"),min_depth=1,max_depth=1) as mon:
            async for p,d in mon:
                seen = True
                print(p[-1])
        if not seen and obj.debug:
            print("- no data.", file=sys.stderr)
        return

    for n in name:
        d = obj.conn.d_get(P(":R.gate")/n)
        yprint(d)


    k["recursive"] = True
    k["raw"] = True
    k["empty"] = True
    await data_get(obj, obj.path, **k)


@cli.command("set", short_help="Add or update a gate entry")
@attr_args
@click.option("-S", "--src", type=P, help="Source (in Moat-Link)")
@click.option("-D", "--dst", type=P, help="Destination (driver specific)")
@click.option("-d", "--ddriver", type=str, help="Driver")
@click.pass_obj
async def set_(obj, last, new, **kw):
    """
    Add/change a gateway entry.
    """

    res = await node_attr(obj, obj.path, **kw)

    if obj.meta:
        yprint(res, stream=obj.stdout)


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


@cli.command()
@click.option("-s", "--state", is_flag=True, help="Also get the current state.")
@click.option("-o", "--only", is_flag=True, help="Value only, nothing fancy.")
@click.option("-p", "--path-only", is_flag=True, help="Value only, nothing fancy.")
@click.option("-D", "--add-date", is_flag=True, help="Add *_date entries")
@click.option("-i", "--ignore", multiple=True, type=P, help="Skip this (sub)tree")
@click.pass_obj
async def monitor(obj, state, only, path_only, add_date, ignore):
    """Monitor a MoaT-Link subtree"""

    cfg = obj.cfg.link
    seen = False
    data = Node()
    plen=len(obj.path)+1


    def pr(res):
        if only:
            res = res.get("data", NotGiven)
        elif path_only:
            res = res["path"]
        elif not obj.meta:
            del res["meta"]
        yprint(res, stream=obj.stdout)
        print("---", file=obj.stdout)
        obj.stdout.flush()

    def set(p,d,m):
        r = dict(path=p,meta=m.repr())
        if d is not NotGiven:
            r["data"] = d
        dd = data.get(p)
        ddm = dd.meta
        n = dd.set(..., d, m)
        if ddm is not None:
            r["last"] = ts = ddm.timestamp-time.time()
            r["_last"] = humandelta(ts, ago=True)
        if n is False:
            r["_***_"]="Obsolete message. Ignored."
        return r

    async with (
        anyio.create_task_group() as tg,
        obj.conn.monitor(cfg.root+obj.path, subtree=True) as res,
    ):
        if state:
            @tg.start_soon
            async def get_tree():
                pl = PathLongener(())
                async with obj.conn.d.walk(obj.path) as mon:
                    async for n,p,d,*m in mon:
                        p = pl.long(n,p)
                        m = MsgMeta.restore(m)
                        res = set(p,d,m)
                        pr(res)

        async for msg in res:
            mp = Path.build(msg.topic[plen:])
            if any(p == mp[: len(p)] for p in ignore):
                continue

            res = set(mp,msg.data,msg.meta)
            pr(res)


@cli.command()
@click.option("-i", "--infile", type=click.Path(), help="File to read (msgpack).")
@click.pass_obj
async def update(obj, infile):
    """Send a list of updates to a MoaT-KV subtree"""
    async with MsgReader(path=infile, codec="std-msgpack") as reader:
        async for msg in reader:
            if not hasattr(msg, "path"):
                continue
            await obj.client.set(obj.path + msg.path, value=msg.value)
