"""
``moat dev heat run``: run heat units (see `moat.dev.heat.system.runner`).
"""

from __future__ import annotations

import inspect

import asyncclick as click

from typing import Any

__all__ = ["cli"]


class _RunCommand(click.Command):
    "Adds the list of units to the help text."

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        from .system.runner import DEFAULT, UNITS  # noqa: PLC0415

        super().format_help_text(ctx, formatter)
        with formatter.section("Units"):
            formatter.write_dl([
                (
                    name if name in DEFAULT else f"{name} (not by default)",
                    (inspect.getdoc(unit) or "").split("\n", 1)[0],
                )
                for name, unit in UNITS.items()
            ])


@click.command(cls=_RunCommand, short_help="Run heat units.")
@click.argument("units", nargs=-1)
@click.pass_obj
async def cli(obj: Any, units: tuple[str, ...]) -> None:
    """
    Run heat units in this process.

    Without arguments, all units but the watchdog are run. Each waits until
    nobody else runs it. A unit that fails restarts with exponential backoff.

    Named units take their service over. A failure ends the command.
    """
    from moat.link.client import Link  # noqa: PLC0415
    from moat.util.systemd import as_service  # noqa: PLC0415

    from .system.runner import DEFAULT, UNITS, run_units  # noqa: PLC0415

    bad = [u for u in units if u not in UNITS]
    if bad:
        raise click.UsageError(f"Unknown unit(s): {' '.join(bad)}. Known: {' '.join(UNITS)}")
    async with as_service(obj) as srv:
        await run_units(
            lambda: Link(obj.cfg.link),
            units or DEFAULT,
            force=bool(units),
            retry=not units,
            task_status=srv,
        )
