"""Command-line interface for irrigation controllers.

``moat db rain at <SITE> controller {show,add,set,delete}``
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.cmds._util import absent, get_one, is_given, list_in_site, require_name, site_of
from moat.db.rain.model import Controller
from moat.lib.run import option_ng


@click.group(name="controller", short_help="Manage irrigation controllers")
@click.option("--name", "-n", type=str, default=None, help="Controller name")
@click.pass_obj
async def cli(obj, name):
    """Manage irrigation controllers."""
    obj.name = name


def opts(c):
    """Scalar options of a :class:`Controller`."""
    c = option_ng("--name", "-n", type=str, help="Rename this controller")(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    c = option_ng("--location", "-l", type=str, help="Where the controller lives")(c)
    c = option_ng("--max-on", "-m", "max_on", type=int, help="Max simultaneously-open valves")(c)
    return c


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one controller, or list all controllers in this site."""
    if obj.name is None:
        seen = False
        for c in list_in_site(obj, Controller):
            seen = True
            print(c.name, file=obj.stdout)
        if not seen:
            print("No controllers defined yet. Use '--help'?", file=sys.stderr)
        return
    c = get_one(obj, Controller, "controller", site=site_of(obj), name=obj.name)
    yprint(c.dump(), stream=obj.stdout)


@cli.command()
@opts
@click.pass_obj
async def add(obj, **kw):
    """Add a controller to this site."""
    name = require_name(obj, "controller")
    if not is_given(kw.get("location", ...)):
        raise click.UsageError("A controller needs --location.")
    absent(obj, Controller, "controller", site=site_of(obj), name=name)
    c = Controller(name=name)
    obj.session.add(c)
    c.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(c.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@click.pass_obj
async def set_(obj, **kw):
    """Modify a controller."""
    name = require_name(obj, "controller")
    c = get_one(obj, Controller, "controller", site=site_of(obj), name=name)
    c.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(c.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a controller (and its valves)."""
    name = require_name(obj, "controller")
    c = get_one(obj, Controller, "controller", site=site_of(obj), name=name)
    obj.session.delete(c)
