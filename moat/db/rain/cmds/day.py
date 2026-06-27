"""Command-line interface for irrigation day definitions.

``moat db rain <SITE> day {show,add,set,delete,time}``

A :class:`Day` is a named union of time fragments (:class:`DayTime`),
scoped **globally** (not per site) — the ``<SITE>`` argument is accepted
for consistency with the rest of the CLI but ignored here, so the dummy
site ``-`` may be used (``moat db rain - day …``). A
:class:`DayRange` (see ``moat db rain <SITE> dayrange``) intersects Days.

Each :class:`DayTime` is a free-form description string (e.g.
``"8:00-12:00"``) belonging to one Day, addressed through the nested
``time`` subgroup::

    moat db rain <SITE> day -n <DAY> time {show,add,set,delete}
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.model import Day, DayTime
from moat.lib.run import option_ng

from ._util import (
    absent,
    get_one,
    list_global,
    require_name,
)


@click.group(name="day", short_help="Manage day definitions (global)")
@click.option("--name", "-n", type=str, default=None, help="Day name")
@click.pass_obj
async def cli(obj, name):
    """Manage global day definitions and their time fragments."""
    obj.name = name


# --- Day itself ---------------------------------------------------------


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one day, or list all days."""
    if obj.name is None:
        seen = False
        for d in list_global(obj, Day):
            seen = True
            print(d.name, file=obj.stdout)
        if not seen:
            print("No days defined yet. Use '--help'?", file=sys.stderr)
        return
    d = get_one(obj, Day, "day", name=obj.name)
    yprint(d.dump(), stream=obj.stdout)


@cli.command()
@click.pass_obj
async def add(obj):
    """Add a day."""
    name = require_name(obj, "day")
    absent(obj, Day, "day", name=name)
    d = Day(name=name)
    obj.session.add(d)
    obj.session.flush()
    yprint(d.dump(), stream=obj.stdout)


@cli.command(name="set")
@option_ng("--name", "-n", type=str, help="Rename this day")
@click.pass_obj
async def set_(obj, **kw):
    """Rename a day."""
    name = require_name(obj, "day")
    d = get_one(obj, Day, "day", name=name)
    d.apply(**kw)
    obj.session.flush()
    yprint(d.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a day (and its time fragments)."""
    name = require_name(obj, "day")
    d = get_one(obj, Day, "day", name=name)
    obj.session.delete(d)


# --- DayTime (nested subgroup) ------------------------------------------


def _day_of(obj) -> Day:
    """Resolve the selected day (``obj.name``) to a row."""
    return get_one(obj, Day, "day", name=require_name(obj, "day"))


@cli.group(name="time", short_help="Manage a day's time fragments")
@click.option("--descr", "-d", type=str, default=None, help="Time-fragment description")
@click.pass_obj
async def time_cli(obj, descr):
    """Manage the time fragments of the selected day."""
    obj.descr = descr


@time_cli.command(name="show")
@click.pass_obj
async def time_show(obj):
    """Show one time fragment, or list all fragments of this day."""
    day = _day_of(obj)
    if obj.descr is None:
        seen = False
        for t in sorted(day.times, key=lambda t: t.descr):
            seen = True
            print(t.descr, file=obj.stdout)
        if not seen:
            print("No time fragments defined yet. Use '--help'?", file=sys.stderr)
        return
    t = get_one(obj, DayTime, "time fragment", day=day, descr=obj.descr)
    yprint(t.dump(), stream=obj.stdout)


@time_cli.command(name="add")
@click.pass_obj
async def time_add(obj):
    """Add a time fragment to this day."""
    day = _day_of(obj)
    descr = obj.descr
    if descr is None:
        raise click.UsageError("The time fragment needs a description. Use '--descr'.")
    absent(obj, DayTime, "time fragment", day=day, descr=descr)
    t = DayTime(descr=descr)
    obj.session.add(t)
    t.apply(day=day.name)
    obj.session.flush()
    yprint(t.dump(), stream=obj.stdout)


@time_cli.command(name="set")
@option_ng("--descr", "-d", type=str, help="Rename this time fragment")
@click.pass_obj
async def time_set(obj, **kw):
    """Modify a time fragment's description."""
    day = _day_of(obj)
    descr = obj.descr
    if descr is None:
        raise click.UsageError("The time fragment needs a description. Use '--descr'.")
    t = get_one(obj, DayTime, "time fragment", day=day, descr=descr)
    t.apply(**kw)
    obj.session.flush()
    yprint(t.dump(), stream=obj.stdout)


@time_cli.command(name="delete")
@click.pass_obj
async def time_delete(obj):
    """Remove a time fragment from this day."""
    day = _day_of(obj)
    descr = obj.descr
    if descr is None:
        raise click.UsageError("The time fragment needs a description. Use '--descr'.")
    t = get_one(obj, DayTime, "time fragment", day=day, descr=descr)
    obj.session.delete(t)
