"""Modify an irrigation site: ``moat db rain <SITE> set``."""

from __future__ import annotations

import asyncclick as click

from moat.util import yprint
from moat.db.rain.model import Site

from ._util import get_one, scale_site_rate, site_dump, site_opts


@click.command()
@site_opts
@click.pass_obj
async def cli(obj, **kw):
    """Modify an irrigation site."""
    site = get_one(obj, Site, "site", name=obj.site_name)
    scale_site_rate(kw)
    site.apply(**kw)
    obj.session.flush()
    yprint(site_dump(site), stream=obj.stdout)
