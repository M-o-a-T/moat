"""Command-line interface for irrigation environment groups.

``moat db rain at <SITE> env {show,add,set,delete}``

An :class:`EnvGroup` bundles environment parameters (rain gating, a
scaling factor, and per-item temperature/wind/sun thresholds) that a
valve draws on. The nested per-item commands are not implemented yet.
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.cmds._util import absent, bool_pair, get_one, list_in_site, require_name, site_of
from moat.db.rain.model import EnvGroup
from moat.lib.run import AliasedGroup, option_ng


@click.group(name="env", cls=AliasedGroup, short_help="Manage environment groups")
@click.option("--name", "-n", type=str, default=None, help="Env-group name")
@click.pass_obj
async def cli(obj, name):
    """Manage irrigation environment groups."""
    obj.name = name


def opts(c):
    """Scalar options of an :class:`EnvGroup`."""
    c = option_ng("--name", "-n", type=str, help="Rename this group")(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    c = option_ng("--factor", "-f", type=float, help="Scaling factor for watering")(c)
    c = click.option("--rain", "rain_set", is_flag=True, help="Gate watering on rain")(c)
    c = click.option("--no-rain", "rain_clr", is_flag=True, help="Don't gate on rain")(c)
    return c


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one env group, or list all env groups in this site."""
    if obj.name is None:
        seen = False
        for g in list_in_site(obj, EnvGroup):
            seen = True
            print(g.name, file=obj.stdout)
        if not seen:
            print("No env groups defined yet. Use '--help'?", file=sys.stderr)
        return
    g = get_one(obj, EnvGroup, "env group", site=site_of(obj), name=obj.name)
    yprint(g.dump(), stream=obj.stdout)


@cli.command()
@opts
@click.pass_obj
async def add(obj, rain_set, rain_clr, **kw):
    """Add an env group to this site."""
    name = require_name(obj, "env group")
    absent(obj, EnvGroup, "env group", site=site_of(obj), name=name)
    kw.update(bool_pair(rain_set, rain_clr, "rain"))
    g = EnvGroup(name=name)
    obj.session.add(g)
    g.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(g.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@click.pass_obj
async def set_(obj, rain_set, rain_clr, **kw):
    """Modify an env group."""
    name = require_name(obj, "env group")
    g = get_one(obj, EnvGroup, "env group", site=site_of(obj), name=name)
    kw.update(bool_pair(rain_set, rain_clr, "rain"))
    g.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(g.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove an env group (valves referencing it are deleted too)."""
    name = require_name(obj, "env group")
    g = get_one(obj, EnvGroup, "env group", site=site_of(obj), name=name)
    obj.session.delete(g)
