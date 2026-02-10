"""
Main supervisor task for Akumuli.

Connects to an Akumuli server and monitors the MoaT-Link configuration
subtree.  Spawns / cancels per-series workers as entries appear or change.
"""

from __future__ import annotations

import anyio
import logging

import asyncakumuli as akumuli

from moat.util import combine_dict
from moat.lib.path import Path

from .model import AkumuliEntry, AkumuliRoot
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
    evt: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the Akumuli connector for one server.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.akumuli`` configuration section.
        server_name: the server entry name inside the config subtree.
        evt: task-status for ``tg.start``.
    """
    prefix = Path.build(cfg["prefix"])
    server_path = prefix / server_name

    # Fetch the server-level config (host/port) from its stored value
    server_data = await link.d_get(server_path)
    srv_cfg = combine_dict(
        (server_data if isinstance(server_data, dict) else {}).get("server", {}),
        cfg.get("server_default", {}),
    )

    async with (
        akumuli.connect(**srv_cfg) as srv,
        anyio.create_task_group() as tg,
    ):
        workers: dict[Path, anyio.CancelScope] = {}

        def _cancel(p: Path) -> None:
            sc = workers.pop(p, None)
            if sc is not None:
                sc.cancel()

        async def _start(p: Path, entry: AkumuliEntry) -> None:
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
                        await run_entry(link, entry, srv, p)
                    except Exception:
                        logger.exception("Worker for %s failed", p)

            await tg.start(_run)

        # Watch the server subtree for configuration entries.
        # mark=True yields None when the initial state is complete.
        async with link.d_watch(
            server_path,
            subtree=True,
            mark=True,
            cls=AkumuliRoot,
        ) as mon:
            evt.started()

            async for msg in mon:
                if msg is None:
                    # Initial state loaded; all entries already spawned.
                    continue
                p, _data = msg
                if not p:
                    # Server-level data changed (host/port); ignore here.
                    continue

                node = mon._node.get(p)  # noqa:SLF001
                if isinstance(node, AkumuliEntry):
                    if node.is_complete():
                        await _start(p, node)
                    else:
                        _cancel(p)
                else:
                    _cancel(p)

        tg.cancel_scope.cancel()
