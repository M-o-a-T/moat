"""Command-line interface: recalculate valve water levels.

``moat db rain at <SITE> recalc [--controller C] [--valve V] [--age D]``

Replays :class:`~moat.db.rain.model.History` to rebuild
:class:`~moat.db.rain.model.Level` rows for the matching valves, starting
from the latest forced level (or the earliest level, promoted to forced)
and walking forward through evaporation, rain runoff, and delivered
flow. Wraps :func:`moat.db.rain.engine.recalculate`.
"""

from __future__ import annotations

from datetime import timedelta

import asyncclick as click

from moat.util import yprint
from moat.db.rain.cmds._util import emit_log
from moat.db.rain.engine import recalculate


@click.command(name="recalc", short_help="Recalculate valve water levels")
@click.option("--controller", "-c", type=str, default=None, help="Limit to one controller")
@click.option("--valve", "-V", type=str, default=None, help="Limit to one valve")
@click.option(
    "--age",
    "-a",
    "age_days",
    type=float,
    default=None,
    help="Replay from this many days back (default: from the latest forced level)",
)
@click.option("--save/--no-save", default=True, help="Persist the recalculated levels")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Narrate every correction")
@click.pass_obj
async def cli(obj, controller, valve, age_days, save, verbose):
    """Recalculate water levels for this site's valves from history."""
    age = timedelta(days=age_days) if age_days is not None else None
    res = recalculate(
        obj.session,
        site=obj.site_name,
        controller=controller,
        valve=valve,
        age=age,
        save=save,
        log=emit_log if verbose else None,
    )
    yprint(res, stream=obj.stdout)
