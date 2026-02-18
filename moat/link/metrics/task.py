"""
Main supervisor task for metrics.

Connects to a metrics backend and monitors the MoaT-Link configuration
subtree.  Spawns / cancels per-series workers as entries appear or change.
"""

from __future__ import annotations

import anyio
import logging

from moat.util import combine_dict
from moat.lib.path import Path

from .backend import get_backend
from .model import MetricsEntry, MetricsServer
from .worker import run_entry

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import Mapping

logger = logging.getLogger(__name__)


async def task(
    link: LinkSender,
    cfg: Mapping,
    server_name: str,
    *,
    task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the metrics connector for one server.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.metrics`` configuration section.
        server_name: the server entry name inside the config subtree.
        task_status: task-status for ``tg.start``.
    """
    prefix = Path.build(cfg["prefix"])
    server_path = prefix / server_name

    # Fetch the server-level config (host/port/backend) from its stored value
    server_data = await link.d_get(server_path)
    srv_cfg = combine_dict(
        (server_data if isinstance(server_data, dict) else {}).get("server", {}),
        cfg.get("server_default", {}),
    )

    # Get the backend from config
    backend = get_backend(srv_cfg, server_name)

    async with (
        backend,
        anyio.create_task_group() as tg,
    ):
        workers: dict[Path, anyio.CancelScope] = {}

        def _cancel(p: Path) -> None:
            sc = workers.pop(p, None)
            if sc is not None:
                sc.cancel()

        async def _start(p: Path, entry: MetricsEntry) -> None:
            _cancel(p)
            if not entry.is_complete():
                logger.warning("Incomplete entry at %s, skipping", p)
                return

            async def _run(
                *,
                task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
            ) -> None:
                with anyio.CancelScope() as sc:
                    workers[p] = sc
                    task_status.started()
                    try:
                        await run_entry(link, entry, backend, p)
                    except Exception:
                        logger.exception("Worker for %s failed", p)

            await tg.start(_run)

        # Watch the server subtree for configuration entries.
        # mark=True yields None when the initial state is complete.
        async with link.d_watch(
            server_path,
            subtree=True,
            mark=True,
            cls=MetricsServer,
        ) as mon:
            task_status.started()

            async for msg in mon:
                if msg is None:
                    # Initial state loaded; all entries already spawned.
                    continue
                p, _data = msg
                if not p:
                    # Server-level data changed (host/port); ignore here.
                    continue

                node = mon._node.get(p)  # noqa:SLF001
                if isinstance(node, MetricsEntry):
                    if node.is_complete():
                        await _start(p, node)
                    else:
                        _cancel(p)
                else:
                    _cancel(p)

        tg.cancel_scope.cancel()
