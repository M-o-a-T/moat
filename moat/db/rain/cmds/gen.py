"""Command-line interface: generate irrigation schedules.

``moat db rain <SITE> gen [--controller C] [--valve V] […]``

Plans valve runs within ``[now+delay, now+delay+horizon)``: forced
(force-on) schedules first, then demand-based slots until each valve's
level deficit is met. Wraps :func:`moat.db.rain.engine.generate_schedule`.
"""

from __future__ import annotations

from datetime import timedelta

import asyncclick as click

from moat.util import yprint
from moat.db.rain.engine import generate_schedule

from ._util import emit_log


@click.command(name="gen", short_help="Generate valve schedules")
@click.option("--controller", "-c", type=str, default=None, help="Limit to one controller")
@click.option("--valve", "-V", type=str, default=None, help="Limit to one valve")
@click.option(
    "--horizon",
    "-a",
    "horizon_days",
    type=float,
    default=1.0,
    help="Days ahead to plan",
)
@click.option(
    "--delay",
    "-d",
    "delay_min",
    type=float,
    default=10.0,
    help="Minutes from now before planning starts",
)
@click.option("--save/--no-save", default=True, help="Persist the generated schedules")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Narrate every decision")
@click.pass_obj
async def cli(obj, controller, valve, horizon_days, delay_min, save, verbose):
    """Generate schedules for this site's valves (driest first)."""
    res = generate_schedule(
        obj.session,
        site=obj.site_name,
        controller=controller,
        valve=valve,
        horizon=timedelta(days=horizon_days),
        delay=timedelta(minutes=delay_min),
        save=save,
        log=emit_log if verbose else None,
    )
    yprint(res, stream=obj.stdout)
