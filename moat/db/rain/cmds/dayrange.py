"""Command-line interface for irrigation day ranges.

``moat db rain <SITE> dayrange {show,add,set,delete}``

A :class:`DayRange` is a **globally**-scoped named intersection of
:class:`Day` unions — the ``<SITE>`` argument is accepted for consistency
but ignored, so the dummy site ``-`` may be used
(``moat db rain - dayrange …``). Groups (see ``moat db rain <SITE>
group``) link to day ranges to express "water on these days".

Days are linked by name; a ``-`` prefix unlinks. A day must exist before
it can be linked.
"""

from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.db.rain.model import DayRange
from moat.lib.run import option_ng

from ._util import absent, get_one, list_global, lookup_errors, require_name


@click.group(name="dayrange", short_help="Manage day ranges (global)")
@click.option("--name", "-n", type=str, default=None, help="Day-range name")
@click.pass_obj
async def cli(obj, name):
    """Manage global day ranges."""
    obj.name = name


def opts(c):
    """Scalar options of a :class:`DayRange`."""
    c = option_ng("--name", "-n", type=str, help="Rename this day range")(c)
    c = option_ng("--comment", "-c", type=str, help="Free-form description")(c)
    return c


def day_opts(c):
    """Day-link options of a :class:`DayRange` (add/remove by name)."""
    c = click.option("--day", "day_add", multiple=True, metavar="NAME", help="Link this day")(c)
    c = click.option("--rm-day", "day_rm", multiple=True, metavar="NAME", help="Unlink this day")(
        c
    )
    return c


def _day_names(day_add, day_rm) -> list[str]:
    """Merge add/remove day names into one list (``-`` marks removal)."""
    return [*day_add, *[f"-{d}" for d in day_rm]]


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one day range, or list all day ranges."""
    if obj.name is None:
        seen = False
        for dr in list_global(obj, DayRange):
            seen = True
            print(dr.name, file=obj.stdout)
        if not seen:
            print("No day ranges defined yet. Use '--help'?", file=sys.stderr)
        return
    dr = get_one(obj, DayRange, "day range", name=obj.name)
    yprint(dr.dump(), stream=obj.stdout)


@cli.command()
@opts
@day_opts
@click.pass_obj
async def add(obj, day_add, day_rm, **kw):
    """Add a day range, optionally linking days."""
    name = require_name(obj, "day range")
    absent(obj, DayRange, "day range", name=name)
    dr = DayRange(name=name)
    obj.session.add(dr)
    with lookup_errors():
        dr.apply(days=_day_names(day_add, day_rm), **kw)
    obj.session.flush()
    yprint(dr.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@day_opts
@click.pass_obj
async def set_(obj, day_add, day_rm, **kw):
    """Modify a day range (rename, comment, day links)."""
    name = require_name(obj, "day range")
    dr = get_one(obj, DayRange, "day range", name=name)
    with lookup_errors():
        dr.apply(days=_day_names(day_add, day_rm), **kw)
    obj.session.flush()
    yprint(dr.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a day range (groups referencing it lose the link)."""
    name = require_name(obj, "day range")
    dr = get_one(obj, DayRange, "day range", name=name)
    obj.session.delete(dr)
