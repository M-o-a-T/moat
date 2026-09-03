# command line interface
from __future__ import annotations

import asyncclick as click

from moat.lib.run import AliasedGroup
from moat.link.announce import announcing
from moat.link.client import Link


@click.group(cls=AliasedGroup, short_help="Manage notifications.")  # pylint: disable=undefined-variable
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


@cli.command()
@click.pass_obj
async def mirror(obj):
    """
    Mirror errors to the notification subtree.

    This command watches the 'error' subtree and writes qualifying
    error entries to the 'notify' subtree so that ``moat link notify run``
    forwards them to the configured backends.

    Mirroring rules are read from a notify-vecs subtree below ``conv.*``
    (configured via ``link.notify.vecs``).  When no vecs path is set,
    all errors at warning level or higher are mirrored.
    """
    from moat.link.notify import ErrorMirror  # noqa: PLC0415

    cfg = obj.cfg.link.notify
    async with announcing(obj.conn) as ann:
        await ErrorMirror(cfg).run(obj.conn, evt=ann)
