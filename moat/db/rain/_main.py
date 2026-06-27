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
@click.argument("site", type=str, nargs=1)
@click.pass_context
async def cli(ctx, site):
    """Irrigation management.

    Manage irrigation sites, controllers, valves, feeds, meters,
    schedules, and the monitoring daemon.
    """
    obj = ctx.obj
    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())
    obj.session = sess
    obj.site_name = site
