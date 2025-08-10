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


@click.group(short_help="Manage notifications.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    Handle notifications.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, name=obj.name))



@cli.command()
@click.option("-b","--backend",type=str,multiple=True,help="Restrict to this backend")
@click.pass_obj
async def run(obj, backend):
    """
    Forward notification messages.

    This command monitors the 'notify' subpath and forwards messages to
    your ntfy.sh instance.
    """
    from moat.link.notify import Notify

    cfg = obj.cfg.link.notify
    if backend:
        cfg.backends = backend
    await Notify(cfg).run(obj.conn)

