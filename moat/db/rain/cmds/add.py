"""Create an irrigation site: ``moat db rain <SITE> add``."""

from __future__ import annotations

import asyncclick as click

from moat.util import yprint
from moat.db.rain.model import Site

from ._util import absent, scale_site_rate, site_dump, site_opts


@click.command()
@site_opts
@click.pass_obj
async def cli(obj, **kw):
    """Create an irrigation site."""
    name = obj.site_name
    absent(obj, Site, "site", name=name)
    site = Site(name=name)
    obj.session.add(site)
    scale_site_rate(kw)
    site.apply(**kw)
    obj.session.flush()
    yprint(site_dump(site), stream=obj.stdout)
