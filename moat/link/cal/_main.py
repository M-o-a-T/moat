"""
Command-line interface for moat.link.cal.

Manages CalDAV calendar polling and alarm publishing.  Calendar
configuration is stored in the MoaT-Link data tree under the
configured ``link.cal.prefix``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from functools import partial

import aiocaldav as caldav
import asyncclick as click
import pytz

from moat.lib.path import Path
from moat.lib.run import AliasedGroup
from moat.link._data import data_get
from moat.link.client import Link

from .util import find_next_alarm

logger = logging.getLogger(__name__)

utc = UTC
now = partial(datetime.now, utc)


@click.group(cls=AliasedGroup, short_help="Manage calendar polling.")
@click.pass_context
async def cli(ctx):
    """
    List known calendars and poll them.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.cal_cfg = obj.cfg.link.cal


@cli.command("run")
@click.argument("name", nargs=1)
@click.pass_obj
async def run_(obj, name):
    """Process calendar alarms.

    Polls the CalDAV calendar configured at ``link.cal.prefix.NAME``
    and publishes the next alarm time to the calendar's ``dst`` path.
    """
    conn = obj.conn
    cal_path = obj.cal_cfg.prefix + Path.build((name,))
    cal_cfg = await conn.d_get(cal_path)
    if not isinstance(cal_cfg, dict):
        raise click.UsageError(f"No calendar configuration at {cal_path!s}")

    try:
        tz = pytz.timezone(cal_cfg["zone"])
    except KeyError:
        tz = utc
        now_l = now
    else:
        now_l = partial(datetime.now, tz)

    try:
        t_scan = datetime.fromtimestamp(cal_cfg["scan"], utc)
    except KeyError:
        t_scan = now()
    interval = timedelta(0, cal_cfg.get("interval", 1800))

    dst = cal_cfg.get("dst")
    if dst is not None:
        dst = Path.build(dst)
    try:
        if dst is not None:
            t_al = await conn.d_get(dst)
        else:
            t_al = now_l()
    except KeyError:
        t_al = now_l()
    else:
        if isinstance(t_al, dict):
            t_al = datetime.fromtimestamp(t_al["time"], tz)

    client = caldav.DAVClient(
        url=cal_cfg["url"],
        username=cal_cfg["user"],
        password=cal_cfg["pass"],
    )
    principal = await client.principal()
    calendar = await principal.calendar(name=cal_cfg["calendar"])
    while True:
        t_now = now_l()
        if t_now < t_scan:
            import anyio  # noqa: PLC0415

            await anyio.sleep((t_scan - t_now).total_seconds())
            cal_cfg = await conn.d_get(cal_path)
            if not isinstance(cal_cfg, dict):
                cal_cfg = {}
            cal_cfg["scan"] = t_scan.timestamp()
            await conn.d_set(cal_path, cal_cfg)
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
                if dst is not None:
                    await conn.d_set(
                        dst,
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
    prefix = obj.cal_cfg.prefix
    path = Path()

    def pm(p):
        if len(p) == 0:
            return p
        elif not isinstance(p[0], int):
            return None
        elif len(p) == 1:
            return Path.build((f"{p[0]:02x}",))
        else:
            return Path.build((f"{p[0]:02x}.{p[1]:12x}",)) + p[2:]

    await data_get(obj.conn, prefix + path, as_dict="_", path_mangle=pm, out=obj.stdout)
