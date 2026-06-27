"""Delete an irrigation site: ``moat db rain <SITE> delete``."""

from __future__ import annotations

import asyncclick as click

from moat.db.rain.model import Site

from ._util import get_one


@click.command()
@click.pass_obj
async def cli(obj):
    """Delete an irrigation site and everything below it."""
    site = get_one(obj, Site, "site", name=obj.site_name)
    obj.session.delete(site)
