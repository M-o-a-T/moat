# command line interface  # noqa: D100
from __future__ import annotations

import asyncclick as click

from moat.link.announce import announcing
from moat.link.client import Link


@click.group(short_help="Manage notifications.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    Handle notifications.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))


@cli.command()
@click.option("-b", "--backend", type=str, multiple=True, help="Restrict to this backend")
@click.pass_obj
async def run(obj, backend):
    """
    Forward notification messages.

    This command monitors the 'notify' subpath and forwards messages to
    your ntfy.sh instance.
    """
    from moat.link.notify import Notify  # noqa: PLC0415

    cfg = obj.cfg.link.notify
    if backend:
        cfg.backends = backend
    async with announcing(obj.conn) as ann:
        await Notify(cfg).run(obj.conn, evt=ann)
