# command line interface
from __future__ import annotations

import datetime
import time
import anyio

import asyncclick as click

from moat.util import P, attrdict
from moat.util.times import ts2iso, humandelta

from moat.link.client import Link
from moat.link._data import data_get, node_attr
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.link.host import cmd_host


@click.group(short_help="Manage host services.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    Each server that's connected to moat-link should run a host service.

    This command manages that service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if ctx.invoked_subcommand != "run":
        obj.conn = await ctx.with_async_resource(Link(cfg))



@cli.command()
@click.option("-m","--main", is_flag=True, help="Main server flag (override)")                 
@click.option("-d","--debug", is_flag=True, help="Debug?")                                     
@click.pass_obj
async def run(obj, main, debug):
    """
    Host management background task.

    "moat link host run" should run on each MoaT-Link connected host.

    It provides keepalive-style ping messages and related services.
    """

    cfg = obj.cfg.link
    if obj.name is not None:
        raise click.UsageError("'moat link host' uses the hostname.")
    async with Link(cfg) as link:
        await cmd_host(link, cfg, main=main, debug=debug)
