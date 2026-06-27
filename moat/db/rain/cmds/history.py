"""Command-line interface for irrigation history and logs.

``moat db rain <SITE> history {show,add,set,delete,log}``

A :class:`History` row is a site-scoped weather/feed sample keyed by
``(site, time)``. The nested ``log`` subgroup manages :class:`Log` event
entries (id-keyed) for the site, optionally tagging a controller or
valve.
"""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import NotGiven, yprint
from moat.db.rain.model import History, Log
from moat.lib.run import option_ng

from ._util import (
    absent,
    get_one,
    is_given,
    lookup_errors,
    parse_dt,
    site_of,
    valve_spec,
)


@click.group(name="history", short_help="Manage weather history and logs")
@click.option("--time", "-t", type=str, default=None, help="Sample time (ISO timestamp)")
@click.pass_obj
async def cli(obj, time):
    """Manage site weather-history samples and event logs."""
    obj.time = time


# --- History samples ----------------------------------------------------


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one sample, or list all samples of this site."""
    site = site_of(obj)
    if obj.time is None:
        seen = False
        with obj.session.execute(
            select(History).where(History.site == site).order_by(History.time)
        ) as rs:
            for h in rs.scalars():
                seen = True
                print(h.time.isoformat(), file=obj.stdout)
        if not seen:
            print("No history samples yet. Use '--help'?", file=sys.stderr)
        return
    h = get_one(obj, History, "history sample", site=site, time=parse_dt(obj.time))
    yprint(h.dump(), stream=obj.stdout)


@cli.command()
@option_ng("--rain", "-r", type=float, help="Rainfall since last sample")
@option_ng("--feed", "-f", type=float, help="Feed volume since last sample")
@option_ng("--temp", "-T", type=float, help="Temperature")
@option_ng("--wind", "-w", type=float, help="Wind speed")
@option_ng("--sun", "-s", type=float, help="Sunshine")
@click.pass_obj
async def add(obj, **kw):
    """Add a weather sample to this site."""
    site = site_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    time = parse_dt(obj.time)
    absent(obj, History, "history sample", site=site, time=time)
    h = History(time=time)
    obj.session.add(h)
    with lookup_errors():
        h.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(h.dump(), stream=obj.stdout)


@cli.command(name="set")
@option_ng("--rain", "-r", type=float, help="Rainfall since last sample")
@option_ng("--feed", "-f", type=float, help="Feed volume since last sample")
@option_ng("--temp", "-T", type=float, help="Temperature")
@option_ng("--wind", "-w", type=float, help="Wind speed")
@option_ng("--sun", "-s", type=float, help="Sunshine")
@click.pass_obj
async def set_(obj, **kw):
    """Modify a weather sample of this site."""
    site = site_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    h = get_one(obj, History, "history sample", site=site, time=parse_dt(obj.time))
    h.apply(**kw)
    obj.session.flush()
    yprint(h.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a weather sample from this site."""
    site = site_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    h = get_one(obj, History, "history sample", site=site, time=parse_dt(obj.time))
    obj.session.delete(h)


# --- Log (nested subgroup) ----------------------------------------------


@cli.group(name="log", short_help="Manage this site's event log")
@click.option("--id", "log_id", type=int, default=None, help="Log entry id")
@click.pass_obj
async def log_cli(obj, log_id):
    """Manage scheduler/operator event entries for this site."""
    obj.log_id = log_id


def _log_of(obj) -> Log:
    """Resolve the selected log entry (``obj.log_id``)."""
    if obj.log_id is None:
        raise click.UsageError("The log entry needs an id. Use '--id'.")
    try:
        return obj.session.one(Log, id=obj.log_id, site=site_of(obj))
    except KeyError:
        raise click.UsageError(f"Log entry {obj.log_id} doesn't exist.") from None


def _log_dump(lg: Log) -> dict:
    """Augment a log's scalar dump with its id (otherwise omitted)."""
    d = lg.dump()
    d["id"] = lg.id
    return d


@log_cli.command(name="show")
@click.pass_obj
async def log_show(obj):
    """Show one log entry, or list all entries of this site."""
    site = site_of(obj)
    if obj.log_id is None:
        seen = False
        with obj.session.execute(
            select(Log).where(Log.site == site).order_by(Log.timestamp)
        ) as rs:
            for lg in rs.scalars():
                seen = True
                print(lg.id, file=obj.stdout)
        if not seen:
            print("No log entries yet. Use '--help'?", file=sys.stderr)
        return
    yprint(_log_dump(_log_of(obj)), stream=obj.stdout)


@log_cli.command(name="add")
@option_ng("--logger", "-l", type=str, help="Logger name")
@option_ng("--text", "-x", type=str, help="Log message")
@option_ng("--timestamp", "-t", type=str, help="Event time (ISO; default now)")
@option_ng("--controller", "-c", type=str, help="Controller name, or '-' to clear")
@click.option("--valve", "-v", type=str, default=None, help="Valve spec 'C:V', or '-' to clear")
@click.pass_obj
async def log_add(obj, valve, **kw):
    """Add a log entry to this site."""
    if not is_given(kw.get("logger", ...)):
        raise click.UsageError("A log entry needs --logger.")
    if not is_given(kw.get("text", ...)):
        raise click.UsageError("A log entry needs --text.")
    ts = kw.pop("timestamp", NotGiven)
    if is_given(ts):
        kw["timestamp"] = parse_dt(ts)
    if valve is not None:
        kw["valve"] = None if valve == "-" else valve_spec(obj, valve)
    lg = Log()
    obj.session.add(lg)
    with lookup_errors():
        lg.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(_log_dump(lg), stream=obj.stdout)


@log_cli.command(name="set")
@option_ng("--logger", "-l", type=str, help="Logger name")
@option_ng("--text", "-x", type=str, help="Log message")
@option_ng("--timestamp", "-t", type=str, help="Event time (ISO)")
@option_ng("--controller", "-c", type=str, help="Controller name, or '-' to clear")
@click.option("--valve", "-v", type=str, default=None, help="Valve spec 'C:V', or '-' to clear")
@click.pass_obj
async def log_set(obj, valve, **kw):
    """Modify a log entry of this site."""
    lg = _log_of(obj)
    ts = kw.pop("timestamp", NotGiven)
    if is_given(ts):
        kw["timestamp"] = parse_dt(ts)
    if valve is not None:
        kw["valve"] = None if valve == "-" else valve_spec(obj, valve)
    lg.apply(**kw)
    obj.session.flush()
    yprint(_log_dump(lg), stream=obj.stdout)


@log_cli.command(name="delete")
@click.pass_obj
async def log_delete(obj):
    """Remove a log entry from this site."""
    obj.session.delete(_log_of(obj))
