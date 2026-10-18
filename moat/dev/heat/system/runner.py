"""
Run heat units (HEAT.md §2.1): one, several, or all of them in one process.

Each unit gets its own MoaT-Link client, so that a unit's liveness (its
service announcement) is its own. Used by ``moat dev heat run`` and the
``moat-heat*`` systemd units.
"""

from __future__ import annotations

import anyio
import logging
from contextlib import suppress

from moat.dev.heat.config import ServiceCfg, load_config
from moat.dev.heat.errors import ErrorsUnit
from moat.dev.heat.flow import FlowUnit
from moat.dev.heat.frost import FrostUnit
from moat.dev.heat.heat_valve import HeatValveUnit
from moat.dev.heat.passthru import PassthruUnit
from moat.dev.heat.pellet import PelletUnit
from moat.dev.heat.pump import PumpUnit
from moat.dev.heat.selector import SelectorUnit
from moat.dev.heat.target import TargetUnit
from moat.dev.heat.watchdog import WatchdogUnit
from moat.lib.path import P
from moat.link.exceptions import ServiceSupplanted

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus
    from contextlib import AbstractAsyncContextManager

    from moat.dev.heat.unit import Unit
    from moat.link.client import LinkSender

    from collections.abc import Callable, Iterable

__all__ = ["DEFAULT", "ERROR_PATH", "UNITS", "run_units"]

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
        PassthruUnit,
        WatchdogUnit,
    )
}
"""Every unit, by name."""

DEFAULT = tuple(n for n in UNITS if n != "watchdog")
"""What ``moat dev heat run`` starts without arguments. The watchdog is
left out: it must not share a process (or host) with the pump unit."""


ERROR_PATH = P("app.heat")
"""A unit's failures are reported to MoaT-Link's error subsystem below this
path, i.e. at ``error.app.heat.<unit>``."""


class _Settled:
    "Tell the runner, once, that a unit runs, waits for its service, or has failed."

    def __init__(self, task_status: TaskStatus[None]) -> None:
        self._ts: TaskStatus[None] | None = task_status

    def __call__(self, *_a: Any) -> None:
        ts, self._ts = self._ts, None
        if ts is not None:
            ts.started()


class _Started:
    "The unit's task status: it is up."

    def __init__(self, settled: _Settled, up: anyio.Event) -> None:
        self._settled = settled
        self._up = up

    def started(self, value: Any = None) -> None:  # noqa: ARG002
        self._settled()
        self._up.set()


def _has(exc: BaseException, cls: type[BaseException]) -> bool:
    "whether ``exc`` is, or is a group containing, a ``cls``"
    if isinstance(exc, BaseExceptionGroup):
        return exc.subgroup(cls) is not None
    return isinstance(exc, cls)


async def _run_unit(
    client: Callable[[], AbstractAsyncContextManager[LinkSender]],
    unit: type[Unit[Any, Any]],
    force: bool,
    retry: bool,
    *,
    task_status: TaskStatus[None],
) -> None:
    """
    Run one unit.

    A failure is reported to MoaT-Link's error subsystem. With @retry it
    is also logged and the unit is restarted, with exponential backoff;
    otherwise it is propagated.
    """
    settled = _Settled(task_status)
    path = ERROR_PATH / unit.name
    svc = ServiceCfg()
    delay = 0.0

    async def recovered(link: LinkSender, up: anyio.Event) -> None:
        nonlocal delay
        await up.wait()
        await anyio.sleep(svc.recovery)
        delay = 0.0
        await link.e_ok(path)

    while True:
        try:
            async with client() as link:
                svc = await load_config(link, "service", ServiceCfg)
                up = anyio.Event()
                try:
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(recovered, link, up)
                        await unit(link).run(
                            force=force, on_wait=settled, task_status=_Started(settled, up)
                        )
                        tg.cancel_scope.cancel()
                except Exception as exc:
                    if not _has(exc, ServiceSupplanted):
                        with anyio.move_on_after(5, shield=True), suppress(Exception):
                            await link.e_exc(path, exc, unit=unit.name)
                    raise
            return
        except Exception as exc:
            if not retry:
                raise
            bo = svc.backoff
            if _has(exc, ServiceSupplanted):
                # Somebody took the service over, on purpose. That's not
                # a failure: wait for them to leave.
                delay = 0.0
                _logger.warning("Unit %s: supplanted", unit.name)
                pause = bo.min
            else:
                delay = pause = min(bo.max, delay * bo.factor if delay else bo.min)
                _logger.error(
                    "Unit %s failed: %r; retry in %.1fs", unit.name, exc, pause, exc_info=exc
                )
        settled()
        await anyio.sleep(pause)


async def run_units(
    client: Callable[[], AbstractAsyncContextManager[LinkSender]],
    names: Iterable[str],
    *,
    force: bool = False,
    retry: bool = False,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Run units until cancelled; signal readiness once all of them run.

    Args:
        client: Opens a MoaT-Link client; called once per unit (and again
            when the unit is restarted).
        names: The units to run.
        force: Take the units' services over from whoever runs them.
            Otherwise, wait until nobody else does.
        retry: Log a unit's failure and restart it, with exponential
            backoff (``cfg.app.heat.service``), instead of propagating
            the error.

    A unit's failure is reported at ``error.app.heat.<unit>`` either way.

    With @retry, "ready" also covers units that wait for their service or
    have failed for now.

    Raises:
        KeyError: an unknown unit.
    """
    units = [UNITS[n] for n in names]
    async with anyio.create_task_group() as tg:
        for u in units:
            await tg.start(_run_unit, client, u, force, retry)
            _logger.info("Unit %s started", u.name)
        task_status.started()
