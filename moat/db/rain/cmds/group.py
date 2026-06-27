"""Command-line interface for irrigation valve groups.

``moat db rain <SITE> group {show,add,set,delete}``

A :class:`Group` is a site-scoped bundle of valves that share a schedule
window. It links to valves (by ``controller:name`` spec) and to day
ranges (by name, globally scoped) — the latter as allowed days
(``--day``) and excluded days (``--xday``); a ``-`` prefix on either
unlinks.

Because :meth:`Group.dump` only emits scalar columns, ``show`` augments
the dump with the linked valves (as ``controller:name``) and day ranges.
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.model import Group
from moat.lib.run import option_ng

from ._util import (
    absent,
    get_one,
    list_in_site,
    lookup_errors,
    require_name,
    site_of,
    valve_spec,
)


@click.group(name="group", short_help="Manage valve groups")
@click.option("--name", "-n", type=str, default=None, help="Group name")
@click.pass_obj
async def cli(obj, name):
    """Manage irrigation valve groups."""
    obj.name = name


def opts(c):
    """Scalar options of a :class:`Group`."""
    c = option_ng("--name", "-n", type=str, help="Rename this group")(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    c = option_ng("--adj", "-a", type=float, help="Watering adjustment factor")(c)
    return c


def link_opts(c):
    """Valve and day-range link options of a :class:`Group`."""
    c = click.option("--valve", "valve_add", multiple=True, metavar="C:V", help="Add a valve")(c)
    c = click.option(
        "--rm-valve", "valve_rm", multiple=True, metavar="C:V", help="Remove a valve"
    )(c)
    c = click.option(
        "--day", "day_add", multiple=True, metavar="NAME", help="Allow on this day range"
    )(c)
    c = click.option(
        "--rm-day", "day_rm", multiple=True, metavar="NAME", help="Drop an allowed day range"
    )(c)
    c = click.option(
        "--xday", "xday_add", multiple=True, metavar="NAME", help="Exclude on this day range"
    )(c)
    c = click.option(
        "--rm-xday", "xday_rm", multiple=True, metavar="NAME", help="Drop an excluded day range"
    )(c)
    return c


def _valves(valve_add, valve_rm, obj) -> tuple[list, list]:
    """Parse add/remove valve specs into Valve objects."""
    add_v = [valve_spec(obj, s) for s in valve_add]
    rm_v = [valve_spec(obj, s) for s in valve_rm]
    return add_v, rm_v


def _names(add, rm) -> list[str]:
    """Merge add/remove name lists (``-`` marks removal)."""
    return [*add, *[f"-{d}" for d in rm]]


def _augmented_dump(g: Group) -> dict:
    """Augment the scalar dump with the group's valves and day ranges."""
    d = g.dump()
    d["valves"] = sorted(f"{v.controller.name}:{v.name}" for v in g.valves)
    d["days"] = sorted(dr.name for dr in g.days)
    d["xdays"] = sorted(dr.name for dr in g.xdays)
    return d


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one group, or list all groups in this site."""
    if obj.name is None:
        seen = False
        for g in list_in_site(obj, Group):
            seen = True
            print(g.name, file=obj.stdout)
        if not seen:
            print("No groups defined yet. Use '--help'?", file=sys.stderr)
        return
    g = get_one(obj, Group, "group", site=site_of(obj), name=obj.name)
    yprint(_augmented_dump(g), stream=obj.stdout)


@cli.command()
@opts
@link_opts
@click.pass_obj
async def add(obj, valve_add, valve_rm, day_add, day_rm, xday_add, xday_rm, **kw):
    """Add a group, optionally linking valves and day ranges."""
    name = require_name(obj, "group")
    absent(obj, Group, "group", site=site_of(obj), name=name)
    add_v, rm_v = _valves(valve_add, valve_rm, obj)
    g = Group(name=name)
    obj.session.add(g)
    with lookup_errors():
        g.apply(
            site=obj.site_name,
            valves=add_v,
            rm_valves=rm_v,
            days=_names(day_add, day_rm),
            xdays=_names(xday_add, xday_rm),
            **kw,
        )
    obj.session.flush()
    yprint(_augmented_dump(g), stream=obj.stdout)


@cli.command(name="set")
@opts
@link_opts
@click.pass_obj
async def set_(obj, valve_add, valve_rm, day_add, day_rm, xday_add, xday_rm, **kw):
    """Modify a group (scalars, valve links, day-range links)."""
    name = require_name(obj, "group")
    g = get_one(obj, Group, "group", site=site_of(obj), name=name)
    add_v, rm_v = _valves(valve_add, valve_rm, obj)
    with lookup_errors():
        g.apply(
            site=obj.site_name,
            valves=add_v,
            rm_valves=rm_v,
            days=_names(day_add, day_rm),
            xdays=_names(xday_add, xday_rm),
            **kw,
        )
    obj.session.flush()
    yprint(_augmented_dump(g), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a group (and its overrides/adjusters)."""
    name = require_name(obj, "group")
    g = get_one(obj, Group, "group", site=site_of(obj), name=name)
    obj.session.delete(g)
