"""
Run heat units (HEAT.md §2.1): one, several, or all of them in one process.

Each unit gets its own MoaT-Link client, so that a unit's liveness (its
service announcement) is its own. Used by ``moat dev heat run`` and the
``moat-heat*`` systemd units.
"""

from __future__ import annotations

import anyio
import logging

from moat.dev.heat.errors import ErrorsUnit
from moat.dev.heat.flow import FlowUnit
from moat.dev.heat.frost import FrostUnit
from moat.dev.heat.heat_valve import HeatValveUnit
from moat.dev.heat.pellet import PelletUnit
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.selector import SelectorUnit
from moat.dev.heat.target import TargetUnit
from moat.dev.heat.watchdog import WatchdogUnit

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus
    from contextlib import AbstractAsyncContextManager

    from moat.dev.heat.unit import Unit
    from moat.link.client import LinkSender

    from collections.abc import Callable, Iterable

__all__ = ["DEFAULT", "UNITS", "run_units"]

_logger = logging.getLogger(__name__)

UNITS: dict[str, type[Unit[Any, Any]]] = {
    u.name: u
    for u in (
        TargetUnit,
        HeatValveUnit,
        FlowUnit,
        PumpUnit,
        PelletUnit,
        SelectorUnit,
        ErrorsUnit,
        FrostUnit,
        WatchdogUnit,
    )
}
"""Every unit, by name."""

DEFAULT = tuple(n for n in UNITS if n != "watchdog")
"""What ``moat dev heat run`` starts without arguments. The watchdog is
left out: it must not share a process (or host) with the pump unit."""


async def _run_unit(
    client: Callable[[], AbstractAsyncContextManager[LinkSender]],
    unit: type[Unit[Any, Any]],
    *,
    task_status: TaskStatus[None],
) -> None:
    async with client() as link:
        await unit(link).run(task_status=task_status)


async def run_units(
    client: Callable[[], AbstractAsyncContextManager[LinkSender]],
    names: Iterable[str],
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Run units until cancelled; signal readiness once all of them run.

    Args:
        client: Opens a MoaT-Link client; called once per unit.
        names: The units to run.

    Raises:
        KeyError: an unknown unit.
    """
    units = [UNITS[n] for n in names]
    async with anyio.create_task_group() as tg:
        for u in units:
            await tg.start(_run_unit, client, u)
            _logger.info("Unit %s runs", u.name)
        task_status.started()
