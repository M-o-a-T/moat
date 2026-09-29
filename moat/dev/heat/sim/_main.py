"""
``moat dev heat sim``: run the plant simulator on MoaT-Link.
"""

from __future__ import annotations

import anyio
from pathlib import Path as FSPath

import asyncclick as click

from typing import Any

__all__ = ["cli"]


@click.command(short_help="Run the plant simulator on MoaT-Link.")
@click.option(
    "-s",
    "--scenario",
    type=click.Path(exists=True, dir_okay=False, path_type=FSPath),
    help="Scenario file (plant setup and event schedule).",
)
@click.option("-t", "--dt", type=float, default=10, help="Simulated seconds per step.")
@click.option("-x", "--scale", type=float, default=1, help="Simulated seconds per real second.")
@click.option("-d", "--duration", type=float, help="Stop after this many simulated seconds.")
@click.pass_obj
async def cli(
    obj: Any, scenario: FSPath | None, dt: float, scale: float, duration: float | None
) -> None:
    """
    Run the plant simulator on MoaT-Link.

    The simulator publishes its sensors at the real ``heat.s.*`` and
    ``temp.*`` paths and reacts to the commands written there, so do not
    run it next to a real plant. Use a separate MoaT-Link root (``link.root``
    in the configuration) for dry runs.
    """
    from moat.link.client import Link  # noqa: PLC0415

    from .link import SimLink  # noqa: PLC0415
    from .scenario import Scenario  # noqa: PLC0415

    sc = Scenario.load(scenario) if scenario is not None else Scenario()
    async with Link(obj.cfg.link) as link:
        sim = SimLink(link, sc, dt=dt, scale=scale)
        with anyio.move_on_after(None if duration is None else duration / scale):
            await sim.run()
