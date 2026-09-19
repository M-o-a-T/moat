"""Command-line interface for irrigation feeds.

``moat db rain at <SITE> feed {show,add,set,delete}``
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.cmds._util import absent, get_one, list_in_site, require_name, site_of
from moat.db.rain.model import Feed
from moat.lib.run import AliasedGroup, option_ng


@click.group(name="feed", cls=AliasedGroup, short_help="Manage water feeds")
@click.option("--name", "-n", type=str, default=None, help="Feed name")
@click.pass_obj
async def cli(obj, name):
    """Manage irrigation feeds (water sources)."""
    obj.name = name


def opts(c):
    """Scalar options of a :class:`Feed`."""
    c = option_ng("--name", "-n", type=str, help="Rename this feed")(c)
    c = option_ng(
        "--flow-monitor",
        "-f",
        "flow_monitor",
        type=str,
        help="Dotted path of the flow-meter sensor ('-' to clear)",
    )(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    c = option_ng("--flow", type=float, help="Nominal flow rate")(c)
    c = option_ng("--max-flow-wait", "max_flow_wait", type=int, help="Seconds to wait for flow")(c)
    c = click.option("--disable", is_flag=True, help="Disable this feed")(c)
    c = click.option("--enable", is_flag=True, help="Re-enable this feed")(c)
    return c


def _disabled_kw(disable: bool, enable: bool) -> dict:
    """Translate the --disable/--enable flags into an apply argument."""
    if disable:
        return {"disabled": True}
    if enable:
        return {"disabled": False}
    return {}


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one feed, or list all feeds in this site."""
    if obj.name is None:
        seen = False
        for f in list_in_site(obj, Feed):
            seen = True
            print(f.name, file=obj.stdout)
        if not seen:
            print("No feeds defined yet. Use '--help'?", file=sys.stderr)
        return
    f = get_one(obj, Feed, "feed", site=site_of(obj), name=obj.name)
    yprint(f.dump(), stream=obj.stdout)


@cli.command()
@opts
@click.pass_obj
async def add(obj, disable, enable, **kw):
    """Add a feed to this site."""
    name = require_name(obj, "feed")
    absent(obj, Feed, "feed", site=site_of(obj), name=name)
    kw.update(_disabled_kw(disable, enable))
    f = Feed(name=name)
    obj.session.add(f)
    f.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(f.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@click.pass_obj
async def set_(obj, disable, enable, **kw):
    """Modify a feed."""
    name = require_name(obj, "feed")
    f = get_one(obj, Feed, "feed", site=site_of(obj), name=name)
    kw.update(_disabled_kw(disable, enable))
    f.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(f.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a feed (valves referencing it are deleted too)."""
    name = require_name(obj, "feed")
    f = get_one(obj, Feed, "feed", site=site_of(obj), name=name)
    obj.session.delete(f)
