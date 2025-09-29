# command line interface  # noqa: D100
from __future__ import annotations

import anyio
import logging
from contextlib import nullcontext

import asyncclick as click

from moat.util import srepr
from moat.link.client import Link
from moat.link.host import HostMon, cmd_host
from moat.util.broadcast import Broadcaster

logger = logging.getLogger(__name__)


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
@click.option("-m", "--main", is_flag=True, help="Main server flag (override)")
@click.option("-d", "--debug", is_flag=True, help="Debug?")
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


@cli.command()
@click.option("-t", "--timeout", type=float, help="Stop after this many seconds.")
@click.pass_obj
async def list(obj, timeout):  # noqa: A001
    """
    Host list.

    "moat link host list" shows the hosts that are currently active.
    """

    with nullcontext() if timeout is None else anyio.move_on_after(timeout):
        async with Broadcaster(100) as br, anyio.create_task_group() as tg:
            tg.start_soon(HostMon(link=obj.conn, cfg=obj.cfg.link).run, br)
            async for h in br:
                print("    UPD  ", h.id, h.state.name, srepr(h.data))
