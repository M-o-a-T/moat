"""Command-line interface: run the irrigation monitor daemon.

``moat db rain <SITE> monitor [--tick N]``

Launches the long-running monitor daemon that subscribes to weather
sensors, generates schedules, dispatches valve commands via moat.link,
and maintains level / history / log rows.  Designed to run as a
``Type=notify`` systemd service (see
``packaging/moat-db-rain/moat-db-rain@.service``).
"""

from __future__ import annotations

import asyncclick as click

from moat.util import as_service, attrdict
from moat.db.rain.monitor import run_monitor


@click.command(name="monitor", short_help="Run the irrigation monitor daemon")
@click.option(
    "--tick",
    "-t",
    "tick_sec",
    type=int,
    default=300,
    help="Scheduler tick interval in seconds",
)
@click.option("--debug", "-d", is_flag=True, default=False, help="Verbose logging")
@click.pass_obj
async def cli(obj, tick_sec, debug):
    """Run the irrigation monitor daemon for this site.

    Subscribes to weather sensors, generates schedules, dispatches valve
    commands via moat.link, and maintains level / history / log rows.

    Designed to run as a systemd ``Type=notify`` service.  The site name
    comes from the positional ``<SITE>`` argument of the parent
    ``moat db rain`` group.
    """
    link = obj.get("link")
    if link is None:
        # Late import so the CLI module loads without moat.link installed.
        from moat.link.client import Link  # noqa: PLC0415

        link_cfg = obj.cfg.get("link")
        if link_cfg is None:
            raise click.UsageError("No moat.link configuration found.")
        link = Link(link_cfg)

    async with (
        link,
        as_service(attrdict(debug=debug)),
    ):
        await run_monitor(
            obj.site_name,
            obj.cfg.db,
            link,
            tick=tick_sec,
            log=lambda msg: print(msg, file=obj.stderr) if debug else None,
        )
