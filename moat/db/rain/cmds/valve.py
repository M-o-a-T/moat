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
from moat.db.rain.model import Controller, Valve
from moat.lib.run import option_ng

from ._util import absent, bool_pair, get_one, is_given, lookup_errors, site_of


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
