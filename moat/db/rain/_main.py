"""Command-line interface for moat.db.rain."""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import yprint
from moat.db import database
from moat.lib.run import load_subgroup

from .model import Site


@load_subgroup(
    sub_pre="moat.db.rain.cmds",
    sub_post="cli",
    ext_pre="moat.db.rain",
    ext_post="_main.cli",
    invoke_without_command=True,
)
@click.argument("site", type=str, nargs=1)
@click.pass_context
async def cli(ctx, site):
    """Irrigation management.

    Manage irrigation sites, controllers, valves, feeds, sensors,
    schedules, and the monitoring daemon.  The site is named before the
    verb — ``moat db rain <SITE> <verb>`` — mirroring ``moat link wago``.

    \b
    Use ``moat db rain -`` to list all sites.
    Use ``moat db rain <SITE>`` (no subcommand) to show one site.
    """
    obj = ctx.obj
    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())
    obj.session = sess
    obj.site_name = site

    if site == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The site '-' triggers a list and precludes subcommands.",
            )
        seen = False
        with sess.execute(select(Site).order_by(Site.name)) as sites:
            for (s,) in sites:
                seen = True
                print(s.name, file=obj.stdout)
        if not seen:
            print("No sites defined yet. Use '--help'?", file=sys.stderr)
        return

    if ctx.invoked_subcommand is None:
        yprint(sess.one(Site, name=site).dump(), stream=obj.stdout)
