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
from moat.link.ntfy import ntfy_bridge


@click.group(short_help="Manage notifications.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    Handle notifications.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.port is not None:
        cfg.client.port = obj.port
    obj.conn = await ctx.with_async_resource(Link(cfg, name=obj.name))



@cli.command()
@click.pass_obj
async def fwd(obj, **k):
    """
    Forward notification messages.

    This command monitors the 'notify' subpath and forwards messages to
    your ntfy.sh instance.
    """
    cfg = obj.cfg["link"]["notify"]
    await ntfy_bridge(obj.conn, cfg["keepalive"], cfg["ntfy"])

