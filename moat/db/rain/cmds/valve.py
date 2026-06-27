"""Command-line interface for irrigation valves.

``moat db rain <SITE> valve {show,add,set,delete}``

A valve is identified by ``(controller, name)`` within the site, and is
linked to a :class:`Feed` (water source) and an :class:`EnvGroup`. Its
``command`` (write) and ``state`` (read-back) paths are MoaT-link
addresses; either may be empty for a monitor-only or control-only valve.
"""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import yprint
from moat.db.rain.model import Controller, Level, Schedule, Valve, ValveOverride
from moat.lib.run import option_ng

from ._util import (
    absent,
    bool_pair,
    get_one,
    is_given,
    lookup_errors,
    parse_dt,
    site_of,
)


@click.group(name="valve", short_help="Manage irrigation valves")
@click.option("--controller", "-c", type=str, default=None, help="Controller this valve is on")
@click.option("--name", "-n", type=str, default=None, help="Valve name")
@click.pass_obj
async def cli(obj, controller, name):
    """Manage irrigation valves."""
    obj.controller = controller
    obj.name = name


def _require_controller(obj) -> str:
    """Return ``obj.controller`` or raise a usage error."""
    controller = obj.controller
    if controller is None:
        raise click.UsageError("The valve needs --controller.")
    return controller


def _controller_of(obj):
    """Resolve the selected controller to a row within the site."""
    return get_one(obj, Controller, "controller", site=site_of(obj), name=_require_controller(obj))


def opts(c):
    """Scalar options of a :class:`Valve` (shared by add and set)."""
    c = option_ng("--name", "-n", type=str, help="Rename this valve")(c)
    c = option_ng("--comment", "-C", type=str, help="Free-form description")(c)
    c = option_ng("--location", "-l", type=str, help="Where the valve is")(c)
    c = option_ng("--flow", "-f", type=float, help="Flow rate when open")(c)
    c = option_ng("--area", "-a", type=float, help="Watered area")(c)
    c = option_ng("--max-level", "-M", "max_level", type=float, help="Max water level")(c)
    c = option_ng("--start-level", "start_level", type=float, help="Level to start at")(c)
    c = option_ng("--stop-level", "stop_level", type=float, help="Level to stop at")(c)
    c = option_ng("--shade", type=float, help="Shade factor")(c)
    c = option_ng("--max-run", "max_run", type=int, help="Max run time (s)")(c)
    c = option_ng("--min-delay", "min_delay", type=int, help="Min pause between runs (s)")(c)
    c = option_ng("--runoff", type=float, help="Runoff fraction")(c)
    c = option_ng("--verbose", type=int, help="Verbosity level")(c)
    c = option_ng("--command", type=str, help="Dotted write path ('-' to clear)")(c)
    c = option_ng("--state", "-S", type=str, help="Dotted read-back path ('-' to clear)")(c)
    c = click.option("--priority", "pri_set", is_flag=True, help="Priority valve")(c)
    c = click.option("--no-priority", "pri_clr", is_flag=True, help="Not a priority valve")(c)
    return c


def _require(kw, key: str, label: str) -> None:
    """Raise if a required add-time option was not supplied."""
    if not is_given(kw.get(key, ...)):
        raise click.UsageError(f"A valve needs --{label}.")


@cli.command(name="show")
@click.pass_obj
async def show_(obj):
    """Show one valve, or list all valves in this site."""
    site = site_of(obj)
    if obj.name is None:
        seen = False
        sel = (
            select(Valve)
            .join(Valve.controller)
            .where(Controller.site == site)
            .order_by(Controller.name, Valve.name)
        )
        with obj.session.execute(sel) as rs:
            for v in rs.scalars():
                seen = True
                print(f"{v.controller.name}:{v.name}", file=obj.stdout)
        if not seen:
            print("No valves defined yet. Use '--help'?", file=sys.stderr)
        return
    v = get_one(obj, Valve, "valve", controller=_controller_of(obj), name=obj.name)
    yprint(v.dump(), stream=obj.stdout)


@cli.command()
@opts
@click.option("--feed", "-F", type=str, help="Feed (water source) for this valve")
@click.option("--envgroup", "-e", type=str, help="Env group governing this valve")
@click.pass_obj
async def add(obj, feed, envgroup, pri_set, pri_clr, **kw):
    """Add a valve to a controller in this site."""
    name = obj.name
    if name is None:
        raise click.UsageError("The valve needs a name. Use '--name'.")
    controller = _require_controller(obj)
    # required parents + scalars
    if feed is None:
        raise click.UsageError("A valve needs --feed.")
    if envgroup is None:
        raise click.UsageError("A valve needs --envgroup.")
    for key, label in (("location", "location"), ("flow", "flow"), ("area", "area")):
        _require(kw, key, label)
    absent(obj, Valve, "valve", controller=_controller_of(obj), name=name)
    kw.update(bool_pair(pri_set, pri_clr, "priority"))
    v = Valve(name=name)
    obj.session.add(v)
    with lookup_errors():
        v.apply(
            site=obj.site_name,
            feed=feed,
            controller=controller,
            envgroup=envgroup,
            **kw,
        )
    obj.session.flush()
    yprint(v.dump(), stream=obj.stdout)


@cli.command(name="set")
@opts
@click.pass_obj
async def set_(obj, pri_set, pri_clr, **kw):
    """Modify a valve (parents are fixed; use delete + add to move it)."""
    name = obj.name
    if name is None:
        raise click.UsageError("The valve needs a name. Use '--name'.")
    v = get_one(obj, Valve, "valve", controller=_controller_of(obj), name=name)
    kw.update(bool_pair(pri_set, pri_clr, "priority"))
    v.apply(site=obj.site_name, **kw)
    obj.session.flush()
    yprint(v.dump(), stream=obj.stdout)


@cli.command(name="delete")
@click.pass_obj
async def delete_(obj):
    """Remove a valve (and its schedules/levels/overrides/logs)."""
    name = obj.name
    if name is None:
        raise click.UsageError("The valve needs a name. Use '--name'.")
    v = get_one(obj, Valve, "valve", controller=_controller_of(obj), name=name)
    obj.session.delete(v)


# --- Nested subgroups: override, schedule, level -----------------------


def _valve_of(obj) -> Valve:
    """Resolve the selected valve (``obj.controller`` + ``obj.name``)."""
    if obj.name is None:
        raise click.UsageError("The valve needs a name. Use '--name'.")
    return get_one(obj, Valve, "valve", controller=_controller_of(obj), name=obj.name)


# ValveOverride: force a valve on/off for a window, keyed by (valve, start).


@cli.group(name="override", short_help="Manage this valve's overrides")
@click.option("--start", "-s", type=str, default=None, help="Override start (ISO timestamp)")
@click.pass_obj
async def override_cli(obj, start):
    """Force a valve on or off for a time window."""
    obj.start = start


@override_cli.command(name="show")
@click.pass_obj
async def override_show(obj):
    """Show one override, or list all overrides of this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        for o in sorted(v.overrides, key=lambda o: o.start):
            print(o.start.isoformat(), file=obj.stdout)
        return
    o = get_one(obj, ValveOverride, "override", valve=v, start=parse_dt(obj.start))
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="add")
@option_ng("--name", "-n", type=str, help="Label for this override")
@option_ng("--duration", "-d", type=int, help="Window length (s)")
@option_ng("--on-level", "on_level", type=float, help="Level to switch on at")
@option_ng("--off-level", "off_level", type=float, help="Level to switch off at")
@click.option("--run", "run_set", is_flag=True, help="Force the valve running")
@click.option("--no-run", "run_clr", is_flag=True, help="Force the valve stopped")
@click.pass_obj
async def override_add(obj, run_set, run_clr, **kw):
    """Add an override to this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    start = parse_dt(obj.start)
    absent(obj, ValveOverride, "override", valve=v, start=start)
    if not is_given(kw.get("duration", ...)):
        raise click.UsageError("An override needs --duration.")
    kw.update(bool_pair(run_set, run_clr, "running"))
    o = ValveOverride(start=start)
    obj.session.add(o)
    with lookup_errors():
        o.apply(valve=v, **kw)
    obj.session.flush()
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="set")
@option_ng("--name", "-n", type=str, help="Label for this override")
@option_ng("--duration", "-d", type=int, help="Window length (s)")
@option_ng("--on-level", "on_level", type=float, help="Level to switch on at")
@option_ng("--off-level", "off_level", type=float, help="Level to switch off at")
@click.option("--run", "run_set", is_flag=True, help="Force the valve running")
@click.option("--no-run", "run_clr", is_flag=True, help="Force the valve stopped")
@click.pass_obj
async def override_set(obj, run_set, run_clr, **kw):
    """Modify an override of this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    o = get_one(obj, ValveOverride, "override", valve=v, start=parse_dt(obj.start))
    kw.update(bool_pair(run_set, run_clr, "running"))
    o.apply(**kw)
    obj.session.flush()
    yprint(o.dump(), stream=obj.stdout)


@override_cli.command(name="delete")
@click.pass_obj
async def override_delete(obj):
    """Remove an override from this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The override needs a start. Use '--start'.")
    o = get_one(obj, ValveOverride, "override", valve=v, start=parse_dt(obj.start))
    obj.session.delete(o)


# Schedule: one planned run, keyed by (valve, start).


@cli.group(name="schedule", short_help="Manage this valve's schedules")
@click.option("--start", "-s", type=str, default=None, help="Run start (ISO timestamp)")
@click.pass_obj
async def schedule_cli(obj, start):
    """Manage planned runs of this valve."""
    obj.start = start


@schedule_cli.command(name="show")
@click.pass_obj
async def schedule_show(obj):
    """Show one schedule, or list all schedules of this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        for s in sorted(v.schedules, key=lambda s: s.start):
            print(s.start.isoformat(), file=obj.stdout)
        return
    s = get_one(obj, Schedule, "schedule", valve=v, start=parse_dt(obj.start))
    yprint(s.dump(), stream=obj.stdout)


@schedule_cli.command(name="add")
@option_ng("--duration", "-d", type=int, help="Run length (s)")
@click.option("--seen", "seen_set", is_flag=True, help="Mark as seen")
@click.option("--no-seen", "seen_clr", is_flag=True, help="Mark as not seen")
@click.option("--changed", "changed_set", is_flag=True, help="Mark as changed")
@click.option("--no-changed", "changed_clr", is_flag=True, help="Mark as not changed")
@click.option("--forced", "forced_set", is_flag=True, help="Mark as forced")
@click.option("--no-forced", "forced_clr", is_flag=True, help="Mark as not forced")
@click.pass_obj
async def schedule_add(
    obj, seen_set, seen_clr, changed_set, changed_clr, forced_set, forced_clr, **kw
):
    """Add a schedule to this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The schedule needs a start. Use '--start'.")
    start = parse_dt(obj.start)
    absent(obj, Schedule, "schedule", valve=v, start=start)
    if not is_given(kw.get("duration", ...)):
        raise click.UsageError("A schedule needs --duration.")
    kw.update(bool_pair(seen_set, seen_clr, "seen"))
    kw.update(bool_pair(changed_set, changed_clr, "changed"))
    kw.update(bool_pair(forced_set, forced_clr, "forced"))
    s = Schedule(start=start)
    obj.session.add(s)
    with lookup_errors():
        s.apply(valve=v, **kw)
    obj.session.flush()
    yprint(s.dump(), stream=obj.stdout)


@schedule_cli.command(name="set")
@option_ng("--duration", "-d", type=int, help="Run length (s)")
@click.option("--seen", "seen_set", is_flag=True, help="Mark as seen")
@click.option("--no-seen", "seen_clr", is_flag=True, help="Mark as not seen")
@click.option("--changed", "changed_set", is_flag=True, help="Mark as changed")
@click.option("--no-changed", "changed_clr", is_flag=True, help="Mark as not changed")
@click.option("--forced", "forced_set", is_flag=True, help="Mark as forced")
@click.option("--no-forced", "forced_clr", is_flag=True, help="Mark as not forced")
@click.pass_obj
async def schedule_set(
    obj, seen_set, seen_clr, changed_set, changed_clr, forced_set, forced_clr, **kw
):
    """Modify a schedule of this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The schedule needs a start. Use '--start'.")
    s = get_one(obj, Schedule, "schedule", valve=v, start=parse_dt(obj.start))
    kw.update(bool_pair(seen_set, seen_clr, "seen"))
    kw.update(bool_pair(changed_set, changed_clr, "changed"))
    kw.update(bool_pair(forced_set, forced_clr, "forced"))
    s.apply(**kw)
    obj.session.flush()
    yprint(s.dump(), stream=obj.stdout)


@schedule_cli.command(name="delete")
@click.pass_obj
async def schedule_delete(obj):
    """Remove a schedule from this valve."""
    v = _valve_of(obj)
    if obj.start is None:
        raise click.UsageError("The schedule needs a start. Use '--start'.")
    s = get_one(obj, Schedule, "schedule", valve=v, start=parse_dt(obj.start))
    obj.session.delete(s)


# Level: a historic capacity sample, keyed by (valve, time).


@cli.group(name="level", short_help="Manage this valve's level samples")
@click.option("--time", "-t", type=str, default=None, help="Sample time (ISO timestamp)")
@click.pass_obj
async def level_cli(obj, time):
    """Manage historic level samples of this valve."""
    obj.time = time


@level_cli.command(name="show")
@click.pass_obj
async def level_show(obj):
    """Show one sample, or list all samples of this valve."""
    v = _valve_of(obj)
    if obj.time is None:
        for lv in sorted(v.levels, key=lambda lv: lv.time):
            print(lv.time.isoformat(), file=obj.stdout)
        return
    lv = get_one(obj, Level, "level sample", valve=v, time=parse_dt(obj.time))
    yprint(lv.dump(), stream=obj.stdout)


@level_cli.command(name="add")
@option_ng("--level", "-l", "level_v", type=float, help="Capacity level")
@option_ng("--flow", "-f", type=float, help="Flow at sample time")
@click.option("--forced", "forced_set", is_flag=True, help="Mark as forced")
@click.option("--no-forced", "forced_clr", is_flag=True, help="Mark as not forced")
@click.pass_obj
async def level_add(obj, forced_set, forced_clr, **kw):
    """Add a level sample to this valve."""
    v = _valve_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    time = parse_dt(obj.time)
    absent(obj, Level, "level sample", valve=v, time=time)
    if not is_given(kw.get("level_v", ...)):
        raise click.UsageError("A level sample needs --level.")
    kw["level"] = kw.pop("level_v")
    kw.update(bool_pair(forced_set, forced_clr, "forced"))
    lv = Level(time=time)
    obj.session.add(lv)
    with lookup_errors():
        lv.apply(valve=v, **kw)
    obj.session.flush()
    yprint(lv.dump(), stream=obj.stdout)


@level_cli.command(name="set")
@option_ng("--level", "-l", "level_v", type=float, help="Capacity level")
@option_ng("--flow", "-f", type=float, help="Flow at sample time")
@click.option("--forced", "forced_set", is_flag=True, help="Mark as forced")
@click.option("--no-forced", "forced_clr", is_flag=True, help="Mark as not forced")
@click.pass_obj
async def level_set(obj, forced_set, forced_clr, **kw):
    """Modify a level sample of this valve."""
    v = _valve_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    lv = get_one(obj, Level, "level sample", valve=v, time=parse_dt(obj.time))
    kw["level"] = kw.pop("level_v")
    kw.update(bool_pair(forced_set, forced_clr, "forced"))
    lv.apply(**kw)
    obj.session.flush()
    yprint(lv.dump(), stream=obj.stdout)


@level_cli.command(name="delete")
@click.pass_obj
async def level_delete(obj):
    """Remove a level sample from this valve."""
    v = _valve_of(obj)
    if obj.time is None:
        raise click.UsageError("The sample needs a time. Use '--time'.")
    lv = get_one(obj, Level, "level sample", valve=v, time=parse_dt(obj.time))
    obj.session.delete(lv)
