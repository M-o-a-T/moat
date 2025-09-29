# command line interface
from __future__ import annotations

import anyio
import logging
from datetime import UTC, datetime, timedelta
from functools import partial

import aiocaldav as caldav
import asyncclick as click
import pytz

from moat.util import P, Path
from moat.kv.data import data_get

from .model import CalRoot
from .util import find_next_alarm

logger = logging.getLogger(__name__)

utc = UTC
now = partial(datetime.now, utc)


@click.group(short_help="Manage calendar polling.")
@click.pass_obj
async def cli(obj):
    """
    List known calendars and poll them.
    """
    obj.data = await CalRoot.as_handler(obj.client)


@cli.command("run")
@click.pass_obj
async def run_(obj):
    """Process calendar alarms"""
    from moat.kv.client import client_scope  # noqa: PLC0415

    kv = await client_scope(**obj.cfg.kv)
    cal_cfg = (await kv.get(P("calendar.test"))).value
    try:
        tz = pytz.timezone(cal_cfg["zone"])
    except KeyError:
        tz = utc
    else:
        now = partial(datetime.now, tz)

    try:
        t_scan = datetime.fromtimestamp(cal_cfg["scan"], utc)
    except KeyError:
        t_scan = now()
    interval = timedelta(0, cal_cfg.get("interval", 1800))

    try:
        t_al = await kv.get(cal_cfg["dst"])
    except KeyError:
        t_al = now()
    else:
        t_al = datetime.fromtimestamp(t_al.value["time"], tz)

    async with caldav.DAVClient(
        url=cal_cfg["url"],
        username=cal_cfg["user"],
        password=cal_cfg["pass"],
    ) as client:
        principal = await client.principal()
        calendar = await principal.calendar(name="privat neu")
        while True:
            t_now = now()
            if t_now < t_scan:
                await anyio.sleep((t_scan - t_now).total_seconds())
                cal_cfg = (await kv.get(P("calendar.test"))).value
                cal_cfg["scan"] = t_scan.timestamp()
                await kv.set(P("calendar.test"), value=cal_cfg)
                t_now = t_scan

            logger.info("Scan %s", t_scan)
            ev, v, ev_t = await find_next_alarm(calendar, zone=tz, now=t_scan)
            t_scan += interval
            t_scan = max(t_now, t_scan).astimezone(tz)

            if ev is None:
                logger.warning("NO EVT")
                continue
            if ev_t <= t_now:
                if t_al != ev_t:
                    # set alarm message
                    logger.warning("ALARM %s %s", v.summary.value, ev_t)
                    await kv.set(
                        cal_cfg["dst"],
                        value=dict(time=int(ev_t.timestamp()), info=v.summary.value),
                    )
                    t_al = ev_t
                    t_scan = t_now + timedelta(0, cal_cfg.get("interval", 1800) / 3)
            elif ev_t < t_scan:
                t_scan = ev_t
                logger.warning("ScanEarly %s", t_scan)
            else:
                logger.warning("ScanLate %s", t_scan)


@cli.command("list")
@click.pass_obj
async def list_(obj):
    """Emit the current state as a YAML file."""
    prefix = obj.cfg.kv.cal.prefix
    path = Path()

    def pm(p):
        if len(p) == 0:
            return p
        elif not isinstance(p[0], int):
            return None
        elif len(p) == 1:
            return Path(f"{p[0]:02x}")
        else:
            return Path(f"{p[0]:02x}.{p[1]:12x}") + p[2:]

    if obj.meta:

        def pm(p):
            return Path(str(prefix + path)) + p

    await data_get(obj.client, prefix + path, as_dict="_", path_mangle=pm, out=obj.stdout)


# @cli.command("attr", help="Mirror a device attribute to/from MoaT-KV")
# @click.option("-d", "--device", help="Device to access.")
# @click.option("-f", "--family", help="Device family to modify.")
# @click.option("-i", "--interval", type=float, help="read value every N seconds")
# @click.option("-w", "--write", is_flag=True, help="Write to the device")
# @click.option("-a", "--attr", "attr_", help="The node's attribute to use", default=":")
# @click.argument("attr", nargs=1)
# @click.argument("path", nargs=1)
# @click.pass_obj
# async def attr__(obj, device, family, write, attr, interval, path, attr_):
#    """Show/add/modify an entry to repeatedly read an 1wire device's attribute.
#
#    You can only set an interval, not a path, on family codes.
#    A path of '-' deletes the entry.
#    If you set neither interval nor path, reports the current
#    values.
#    """
#    path = P(path)
#    prefix = obj.cfg.kv.cal.prefix
#    if (device is not None) + (family is not None) != 1:
#        raise click.UsageError("Either family or device code must be given")
#    if interval and write:
#        raise click.UsageError("Writing isn't polled")
#
#    remove = False
#    if len(path) == 1 and path[0] == "-":
#        path = ()
#        remove = True
#
#    if family:
#        if path:
#            raise click.UsageError("You cannot set a per-family path")
#        fd = (int(family, 16),)
#    else:
#        f, d = device.split(".", 2)[0:2]
#        fd = (int(f, 16), int(d, 16))
#
#    attr = P(attr)
#    attr_ = P(attr_)
#    if remove:
#        res = await obj.client.delete(prefix + fd + attr)
#    else:
#        val = dict()
#        if path:
#            val["src" if write else "dest"] = path
#        if interval:
#            val["interval"] = interval
#        if len(attr_):
#            val["src_attr" if write else "dest_attr"] = attr_
#
#        res = await obj.client.set(prefix + fd + attr, value=val)
#
#    if res is not None and obj.meta:
#        yprint(res, stream=obj.stdout)
#
#
# @cli.command("set")
# @click.option("-d", "--device", help="Device to modify.")
# @click.option("-f", "--family", help="Device family to modify.")
# @attr_args
# @click.argument("subpath", nargs=1, type=P, default=P(":"))
# @click.pass_obj
# async def set_(obj, device, family, subpath, **kw):
#    """Set or delete some random attribute.
#
#    For deletion, use '-e ATTR -'.
#    """
#    if (device is not None) + (family is not None) != 1:
#        raise click.UsageError("Either family or device code must be given")
#
#    if family:
#        fd = (int(family, 16),)
#        if len(subpath):
#            raise click.UsageError("You can't use a subpath here.")
#    else:
#        f, d = device.split(".", 2)[0:2]
#        fd = (int(f, 16), int(d, 16))
#
#    res = await node_attr(obj, obj.cfg.kv.cal.prefix + fd + subpath, **kw)
#    if res and obj.meta:
#        yprint(res, stream=obj.stdout)
#
#
# @cli.command("server")
# @click.option("-h", "--host", help="Host name of this server.")
# @click.option("-p", "--port", help="Port of this server.")
# @click.option("-d", "--delete", is_flag=True, help="Delete this server.")
# @click.argument("name", nargs=-1)
# @click.pass_obj
# async def server_(obj, name, host, port, delete):
#    """
#    Configure a server.
#
#    No arguments: list them.
#    """
#    prefix = obj.cfg.kv.cal.prefix
#    if not name:
#        if host or port or delete:
#            raise click.UsageError("Use a server name to set parameters")
#        async for r in obj.client.get_tree(
#            prefix | "server", min_depth=1, max_depth=1
#        ):
#            print(r.path[-1], file=obj.stdout)
#        return
#    elif len(name) > 1:
#        raise click.UsageError("Only one server allowed")
#    name = name[0]
#    if host or port:
#        if delete:
#            raise click.UsageError("You can't delete and set at the same time.")
#        value = attrdict()
#        if host:
#            value.host = host
#        if port:
#            if port == "-":
#                value.port = NotGiven
#            else:
#                value.port = int(port)
#    elif delete:
#        res = await obj.client.delete_tree(prefix | "server" | name, nchain=obj.meta)
#        if obj.meta:
#            yprint(res, stream=obj.stdout)
#        return
#    else:
#        value = None
#    res = await node_attr(
#        obj, prefix | "server" | name, ((P("server"), value),),(),())
#    if res and obj.meta:
#        yprint(res, stream=obj.stdout)
#
#
# @cli.command()
# @click.pass_obj
# @click.argument("server", nargs=-1)
# async def monitor(obj, server):
#    """Stand-alone task to monitor one or more OWFS servers."""
#    from .task import task
#
#    async with as_service(obj) as srv:
#        await task(obj.client, obj.cfg, server, srv)
