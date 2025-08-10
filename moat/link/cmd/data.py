# command line interface
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


@click.group(short_help="Manage data.", invoke_without_command=True)  # pylint: disable=undefined-variable
@click.option("-m","--meta",is_flag=True,help="include metadata")
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path,meta):
    """
    This subcommand accesses the data stored in the MoaT-Link server.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, name=obj.name))
    obj.meta=meta
    if ctx.invoked_subcommand is None:
        res = await data_get(obj.conn,path, meta=obj.meta,out=obj.stdout, recursive=False)
    else:
        obj.path = path



@cli.command()
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use "
    "for values. Default: return as list",
)
@click.option(
    "-m",
    "--maxdepth",
    type=int,
    default=None,
    help="Limit recursion depth. Default: whole tree",
)
@click.option(
    "-M",
    "--mindepth",
    type=int,
    default=None,
    help="Starting depth. Default: whole tree",
)
@click.option("-r", "--recursive", is_flag=True, help="Read a complete subtree")
@click.option("-e", "--empty", is_flag=True, help="Include empty nodes")
@click.option("-R", "--raw", is_flag=True, help="Print string values without quotes etc.")
@click.option("-D", "--add-date", is_flag=True, help="Add *_date entries")
@click.pass_obj
async def get(obj, **k):
    """
    Read a MoaT-KV value.

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """

    await data_get(obj.conn, obj.path, meta=obj.meta, **k)


@cli.command("list")
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use "
    "for values. Default: return as list",
)
@click.option(
    "-m",
    "--maxdepth",
    type=int,
    default=1,
    help="Limit recursion depth. Default: 1 (single layer).",
)
@click.option(
    "-M",
    "--mindepth",
    type=int,
    default=1,
    help="Starting depth. Default: 1 (single layer).",
)
@click.pass_obj
async def list_(obj, **k):
    """
    List MoaT-KV values.

    This is like "get" but with "--mindepth=1 --maxdepth=1 --recursive --empty"

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """

    k["recursive"] = True
    k["raw"] = True
    k["empty"] = True
    await data_get(obj.conn, obj.path, meta=obj.meta, **k)


@cli.command("set", short_help="Add or update an entry")
@attr_args
@click.option("-l", "--last", nargs=2, help="Previous change entry (node serial)")
@click.option("-n", "--new", is_flag=True, help="This is a new entry.")
@click.pass_obj
async def set_(obj, last, new, **kw):
    """
    Store a value at some MoaT-KV position.

    If you update a value you can use "--last" to ensure that no other
    change arrived between reading and writing the entry.

    When adding a new entry use "--new" to ensure that you don't
    accidentally overwrite something.

    MoaT-KV entries typically are mappings. Use a colon as the path if you
    want to replace the top level.
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
@click.option("-i", "--infile", type=click.Path(), help="File to read.")
@click.option("-C", "--codec", type=str, default="yaml", help="Codec to use (default: yaml).")
@click.pass_obj
async def update(obj, infile, codec):
    """Write a list of updates to a MoaT-Link subtree"""
    async with MsgReader(path="/dev/stdin" if infile == "-" else infile, codec=codec) as reader:
        async for msg in reader:
            if isinstance(msg,dict):
                p = msg["path"]
                v = msg["value"]
            else:
                p,v,*_m = msg
            await obj.conn.d_set(obj.path + p, v)
