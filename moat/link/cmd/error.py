# command line interface  # noqa: D100
from __future__ import annotations

import anyio
from contextlib import nullcontext

import asyncclick as click

from moat.util import NotGiven, P, attr_args, yprint
from moat.link._data import data_get, node_attr
from moat.link.client import Link
from moat.link.meta import MsgMeta


@click.group(short_help="Manage data.", invoke_without_command=True)  # pylint: disable=undefined-variable
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path):
    """
    This subcommand reads and manipulates errors stored in the MoaT-Link service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    path = P("error") + path
    if ctx.invoked_subcommand is None:
        await data_get(obj.conn, path, meta=True, out=obj.stdout, recursive=False)
    else:
        obj.path = path


@cli.command
@click.pass_obj
async def get(obj, **k):
    """
    Retrieve a MoaT-Link error entry.

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """
    await data_get(obj.conn, obj.path, meta=obj.meta, **k)


@cli.command("set", short_help="Update an entry")
@click.option("-k/-K", "--ok/--bad", is_flag=True, help="Mark as ok / not ok")
@attr_args
@click.pass_obj
async def set_(obj, ok, **kw):
    """
    Update some MoaT-Link error entry.
    """
    if ok is not None:
        kw["eval_"]["ok"] = repr(ok)
    res = await node_attr(obj, obj.path, **kw)

    if obj.meta:
        yprint(res, stream=obj.stdout)


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

    You might want to use "--before" flag to ensure that no other change
    arrived after you viewed the data in question.

    Non-recursively deleting an entry with children works and does *not*
    affect the child entries.

    The root entry cannot be deleted.
    """
    args = {}
    if recursive:
        args["rec"] = recursive
    if before:
        args["ts"] = before
    res = await obj.conn.d.delete(obj.path, **args)
    if obj.meta:
        res = dict(data=res[0], meta=MsgMeta.restore(res[1:]).repr())
    else:
        res = res[0]
    yprint(res, stream=obj.stdout)


@cli.command()
@click.option("-m", "--mode", type=str, help="Retrieval mode", default="s")
@click.option("-M", "--mark", is_flag=True, help="Retrieval mode")
@click.option("-s", "--subtree", is_flag=True, help="Read the whole tree.")
@click.option("-D", "--add-date", is_flag=True, help="Add *_date entries")
@click.option("-i", "--ignore", multiple=True, type=P, help="Skip this (sub)tree")
@click.option("-n", "--min-length", type=int, help="Minimum path length")
@click.option("-N", "--max-length", type=int, help="Maximum path length")
@click.option("-a", "--max-age", type=int, help="Skip entries older than N seconds")
@click.option("-t", "--timeout", type=int, help="Stop reading after N seconds")
@click.pass_obj
async def monitor(
    obj,
    mode,
    add_date,  # noqa: ARG001
    ignore,
    mark,
    subtree,
    min_length,
    max_length,
    max_age,
    timeout,
):
    """Monitor a MoaT-Link subtree.

    The mode can be:
    * c/current   read current data from the server
    * u/update    read updates from MQTT
    * s/stream    current plus updates
    * m/mqtt      subscribe to MQTT stream, including retained data
    """

    match mode:
        case "c" | "current":
            state = True
        case "u" | "update":
            state = False
        case "s" | "stream":
            state = None
        case "m" | "mqtt":
            state = NotGiven
        case _:
            raise click.UsageError("Mode must be current|update|stream|mqtt")
    if mark and state is not None:
        raise click.UsageError("You can only add a mark in Stream mode")

    def pm(p):
        for ip in ignore:
            if len(p) >= len(ip) and p[: len(ip)] == ip:
                return True
        return False

    with anyio.move_on_after(timeout) if timeout else nullcontext():
        async with obj.conn.d_watch(
            obj.path,
            state=state,
            mark=mark,
            meta=True,
            subtree=subtree,
            max_length=max_length,
            min_length=min_length,
            age=max_age,
        ) as mon:
            async for res in mon:
                if res is None:
                    res = "*** Snapshot data ends ***"  # noqa:PLW2901
                yprint(res, stream=obj.stdout)
                print("---", file=obj.stdout)
                obj.stdout.flush()
