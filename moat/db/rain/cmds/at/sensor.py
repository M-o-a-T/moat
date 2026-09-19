"""Command-line interface for irrigation sensors.

``moat db rain at <SITE> sensor {show,add,set,delete}``

A sensor is identified by ``(site, kind, name)`` — ``kind`` is one of
``rain`` / ``temp`` / ``wind`` / ``sun`` and is immutable once set.
"""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import yprint
from moat.db.rain.cmds._util import absent, get_one, is_given, require_name, site_of
from moat.db.rain.model import Sensor
from moat.lib.run import AliasedGroup, option_ng

KINDS = ["rain", "temp", "wind", "sun"]


@click.group(name="sensor", cls=AliasedGroup, short_help="Manage weather/flow sensors")
@click.option("--kind", "-k", type=click.Choice(KINDS), default=None, help="Sensor kind")
@click.option("--name", "-n", type=str, default=None, help="Sensor name")
@click.pass_obj
async def cli(obj, kind, name):
    """Manage irrigation sensors (rain/temp/wind/sun meters)."""
    obj.kind = kind
    obj.name = name


def opts(c):
    """Scalar options of a :class:`Sensor`."""
    c = option_ng("--name", "-n", type=str, help="Rename this sensor")(c)
    c = option_ng(
        "--state", "-s", type=str, help="Dotted read/subscribe path (required to create)"
    )(c)
    c = option_ng("--weight", "-w", type=int, help="Weight for averaging")(c)
    return c


def _require_kind(obj) -> str:
    """Return ``obj.kind`` or raise a usage error."""
    kind = obj.kind
    if kind is None:
        raise click.UsageError("The sensor needs --kind.")
    return kind


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one sensor, or list all sensors in this site."""
    site = site_of(obj)
    if obj.name is None:
        sel = select(Sensor).where(Sensor.site == site).order_by(Sensor.kind, Sensor.name)
        if obj.kind is not None:
            sel = sel.where(Sensor.kind == obj.kind)
        seen = False
        with obj.session.execute(sel) as rs:
            for s in rs.scalars():
                seen = True
                print(f"{s.kind}:{s.name}", file=obj.stdout)
        if not seen:
            print("No sensors defined yet. Use '--help'?", file=sys.stderr)
        return
    kind = _require_kind(obj)
    s = get_one(obj, Sensor, "sensor", site=site, kind=kind, name=obj.name)
    yprint(s.dump(), stream=obj.stdout)


@cli.command()
@opts
@click.pass_obj
async def add(obj, **kw):
    """Add a sensor to this site."""
    name = require_name(obj, "sensor")
    kind = _require_kind(obj)
    if not is_given(kw.get("state", ...)):
        raise click.UsageError("A sensor needs --state.")
    absent(obj, Sensor, "sensor", site=site_of(obj), kind=kind, name=name)
    s = Sensor(name=name)
    obj.session.add(s)
    s.apply(site=obj.site_name, kind=kind, **kw)
    obj.session.flush()
    yprint(s.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@click.pass_obj
async def set_(obj, **kw):
    """Modify a sensor (its kind is immutable)."""
    name = require_name(obj, "sensor")
    kind = _require_kind(obj)
    s = get_one(obj, Sensor, "sensor", site=site_of(obj), kind=kind, name=name)
    s.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(s.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a sensor."""
    name = require_name(obj, "sensor")
    kind = _require_kind(obj)
    s = get_one(obj, Sensor, "sensor", site=site_of(obj), kind=kind, name=name)
    obj.session.delete(s)
