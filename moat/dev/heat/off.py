"""
``moat dev heat off``: emergency shutdown of the heat pump.
"""

from __future__ import annotations

import asyncclick as click

from typing import Any

__all__ = ["cli"]


@click.command(short_help="Shut the heat pump down safely (emergency).")
@click.pass_obj
async def cli(obj: Any) -> None:
    """
    Shut the heat pump down safely.

    Takes over the pump service (the running pump unit exits), switches
    the heat pump off, keeps the water pump running until the heat
    exchanger has cooled down, then stops it. See HEAT.md §2.6.
    """
    from moat.link.client import Link  # noqa: PLC0415

    from .emergency import emergency_shutdown  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        res = await emergency_shutdown(link, from_pump=False)
    print(res)
