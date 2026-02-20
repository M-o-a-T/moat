# command line interface  # noqa: D100
from __future__ import annotations

import asyncclick as click

from moat.util import yprint
from moat.lib.path import P
from moat.link.client import Link
from moat.link.schema import schema_path


@click.group(short_help="Manage schemas.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    This subcommand reads schema entries stored in the MoaT-Link service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, common=True))


@cli.command()
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def get(obj, path):
    """
    Retrieve the schema for a path.
    """
    res = await obj.conn.d_search(schema_path(path))
    yprint(res, stream=obj.stdout)
