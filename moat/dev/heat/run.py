"""
``moat dev heat run``: run heat units (see `moat.dev.heat.system.runner`).
"""

from __future__ import annotations

import asyncclick as click

from typing import Any

__all__ = ["cli"]


@click.command(short_help="Run heat units.")
@click.argument("units", nargs=-1)
@click.pass_obj
async def cli(obj: Any, units: tuple[str, ...]) -> None:
    """
    Run the named units (default: all but the watchdog) in this process.

    Talks to systemd (readiness, watchdog) when started as a service.
    """
    from moat.link.client import Link  # noqa: PLC0415
    from moat.util.systemd import as_service  # noqa: PLC0415

    from .system.runner import DEFAULT, UNITS, run_units  # noqa: PLC0415

    bad = [u for u in units if u not in UNITS]
    if bad:
        raise click.UsageError(f"Unknown unit(s): {' '.join(bad)}. Known: {' '.join(UNITS)}")
    async with as_service(obj) as srv:
        await run_units(lambda: Link(obj.cfg.link), units or DEFAULT, task_status=srv)
