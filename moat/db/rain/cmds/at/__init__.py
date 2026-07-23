"""Site-specific subcommands for ``moat db rain at <SITE>``.

This sub-package hosts the site-scoped commands (controllers, valves,
feeds, sensors, groups, environment groups, history, gen, recalc,
monitor) and the site-management verbs (add, set, delete). They are
loaded by the ``at`` group defined here, which takes the mandatory
``SITE`` argument and sets ``obj.site_name`` for every subcommand.
"""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import yprint
from moat.db.rain.cmds._util import site_dump
from moat.db.rain.model import Site
from moat.lib.run import load_subgroup


@load_subgroup(
    sub_pre="moat.db.rain.cmds.at",
    sub_post="cli",
    invoke_without_command=True,
)
@click.argument("site", type=str, nargs=1)
@click.pass_context
async def cli(ctx, site):
    """Site-specific irrigation management.

    Manage one irrigation site's controllers, valves, feeds, sensors,
    groups, schedules, and the monitoring daemon. The site is named
    immediately after ``at``::

        moat db rain at <SITE> <verb>

    Use ``moat db rain at <SITE>`` (no subcommand) to show one site.
    Use ``moat db rain at -`` to list all sites.
    """
    obj = ctx.obj
    obj.site_name = site

    if site == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The site '-' is a dummy; it cannot be used with a subcommand.",
            )
        seen = False
        with obj.session.execute(select(Site).order_by(Site.name)) as sites:
            for (s,) in sites:
                seen = True
                print(s.name, file=obj.stdout)
        if not seen:
            print("No sites defined yet. Use '--help'?", file=sys.stderr)
        return

    if ctx.invoked_subcommand is None:
        yprint(site_dump(obj.session.one(Site, name=site)), stream=obj.stdout)
