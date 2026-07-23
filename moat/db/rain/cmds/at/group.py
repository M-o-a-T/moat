"""Command-line interface for irrigation valve groups.

``moat db rain at <SITE> group {show,add,set,delete}``

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
from moat.db.rain.cmds._util import (
    absent,
    bool_pair,
    get_one,
    is_given,
    list_in_site,
    lookup_errors,
    parse_dt,
    require_name,
    site_of,
    valve_spec,
)
from moat.db.rain.model import Group, GroupAdjust, GroupOverride
from moat.lib.run import option_ng


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


# --- Nested subgroups: override, adjust ---------------------------------


def _group_of(obj) -> Group:
    """Resolve the selected group (``obj.name``) within the site."""
    return get_one(obj, Group, "group", site=site_of(obj), name=require_name(obj, "group"))


# GroupOverride: a window allowing/blocking the group's schedule, keyed by
# (group, start).


@cli.group(name="override", short_help="Manage this group's overrides")
@click.option("--start", "-s", type=str, default=None, help="Override start (ISO timestamp)")
@click.pass_obj
async def override_cli(obj, start):
    """Allow or block the group's schedule for a time window."""
    obj.start = start


@override_cli.command(name="show")
@click.pass_obj
async def override_show(obj):
    """Show one override, or list all overrides of this group."""
    g = _group_of(obj)
    if obj.start is None:
        for o in sorted(g.overrides, key=lambda o: o.start):
            print(o.start.isoformat(), file=obj.stdout)
        return
    o = get_one(obj, GroupOverride, "override", group=g, start=parse_dt(obj.start))
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="add")
@option_ng("--name", "-n", type=str, help="Label for this override")
@option_ng("--duration", "-d", type=int, help="Window length (s)")
@option_ng("--on-level", "on_level", type=float, help="Level to switch on at")
@option_ng("--off-level", "off_level", type=float, help="Level to switch off at")
@click.option("--allow", "allow_set", is_flag=True, help="Allow watering in this window")
@click.option("--no-allow", "allow_clr", is_flag=True, help="Block watering in this window")
@click.pass_obj
async def override_add(obj, allow_set, allow_clr, **kw):
    """Add an override to this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    start = parse_dt(obj.start)
    absent(obj, GroupOverride, "override", group=g, start=start)
    if not is_given(kw.get("duration", ...)):
        raise click.UsageError("An override needs --duration.")
    kw.update(bool_pair(allow_set, allow_clr, "allowed"))
    o = GroupOverride(start=start)
    obj.session.add(o)
    with lookup_errors():
        o.apply(site=obj.site_name, group=g.name, **kw)
    obj.session.flush()
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="set")
@option_ng("--name", "-n", type=str, help="Label for this override")
@option_ng("--duration", "-d", type=int, help="Window length (s)")
@option_ng("--on-level", "on_level", type=float, help="Level to switch on at")
@option_ng("--off-level", "off_level", type=float, help="Level to switch off at")
@click.option("--allow", "allow_set", is_flag=True, help="Allow watering in this window")
@click.option("--no-allow", "allow_clr", is_flag=True, help="Block watering in this window")
@click.pass_obj
async def override_set(obj, allow_set, allow_clr, **kw):
    """Modify an override of this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    o = get_one(obj, GroupOverride, "override", group=g, start=parse_dt(obj.start))
    kw.update(bool_pair(allow_set, allow_clr, "allowed"))
    o.apply(**kw)
    obj.session.flush()
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="delete")
@click.pass_obj
async def override_delete(obj):
    """Remove an override from this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    o = get_one(obj, GroupOverride, "override", group=g, start=parse_dt(obj.start))
    obj.session.delete(o)


# GroupAdjust: a dated demand multiplier, keyed by (group, start).


@cli.group(name="adjust", short_help="Manage this group's adjusters")
@click.option("--start", "-s", type=str, default=None, help="Adjuster start (ISO timestamp)")
@click.pass_obj
async def adjust_cli(obj, start):
    """Manage dated demand multipliers for this group."""
    obj.start = start


@adjust_cli.command(name="show")
@click.pass_obj
async def adjust_show(obj):
    """Show one adjuster, or list all adjusters of this group."""
    g = _group_of(obj)
    if obj.start is None:
        for a in sorted(g.adjusters, key=lambda a: a.start):
            print(a.start.isoformat(), file=obj.stdout)
        return
    a = get_one(obj, GroupAdjust, "adjuster", group=g, start=parse_dt(obj.start))
    yprint(a.dump(), stream=obj.stdout)


@adjust_cli.command(name="add")
@option_ng("--factor", "-f", type=float, help="Demand multiplier")
@click.pass_obj
async def adjust_add(obj, **kw):
    """Add an adjuster to this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The adjuster needs a start. Use '--start'.")
    start = parse_dt(obj.start)
    absent(obj, GroupAdjust, "adjuster", group=g, start=start)
    if not is_given(kw.get("factor", ...)):
        raise click.UsageError("An adjuster needs --factor.")
    a = GroupAdjust(start=start)
    obj.session.add(a)
    with lookup_errors():
        a.apply(site=obj.site_name, group=g.name, **kw)
    obj.session.flush()
    yprint(a.dump(), stream=obj.stdout)


@adjust_cli.command(name="set")
@option_ng("--factor", "-f", type=float, help="Demand multiplier")
@click.pass_obj
async def adjust_set(obj, **kw):
    """Modify an adjuster of this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The adjuster needs a start. Use '--start'.")
    a = get_one(obj, GroupAdjust, "adjuster", group=g, start=parse_dt(obj.start))
    a.apply(**kw)
    obj.session.flush()
    yprint(a.dump(), stream=obj.stdout)


@adjust_cli.command(name="delete")
@click.pass_obj
async def adjust_delete(obj):
    """Remove an adjuster from this group."""
    g = _group_of(obj)
    if obj.start is None:
        raise click.UsageError("The adjuster needs a start. Use '--start'.")
    a = get_one(obj, GroupAdjust, "adjuster", group=g, start=parse_dt(obj.start))
    obj.session.delete(a)
