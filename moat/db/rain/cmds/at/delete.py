"""Delete an irrigation site: ``moat db rain at <SITE> delete``."""

from __future__ import annotations

import asyncclick as click

from moat.db.rain.cmds._util import get_one
from moat.db.rain.model import Site


@click.command()
@click.pass_obj
async def cli(obj):
    """Delete an irrigation site and everything below it."""
    site = get_one(obj, Site, "site", name=obj.site_name)
    obj.session.delete(site)
