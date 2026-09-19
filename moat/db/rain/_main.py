"""Command-line interface for moat.db.rain."""

from __future__ import annotations

import asyncclick as click

from moat.db import database
from moat.lib.run import load_subgroup


@load_subgroup(
    sub_pre="moat.db.rain.cmds",
    sub_post="cli",
    ext_pre="moat.db.rain",
    ext_post="_main.cli",
    invoke_without_command=True,
)
@click.pass_context
async def cli(ctx):
    """Irrigation management.

    Manage irrigation sites, controllers, valves, feeds, sensors,
    schedules, and the monitoring daemon.

    Site-specific subcommands are grouped under ``at <SITE>``::

        moat db rain at <SITE> <verb>

    Global subcommands (day, dayrange) that don't need a site are
    called directly::

        moat db rain day <verb>
        moat db rain dayrange <verb>
    """
    obj = ctx.obj
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return
    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())
    obj.session = sess
