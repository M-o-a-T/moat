"""
Main supervisor task for the KNX connector.

Connects to a single KNX gateway and monitors the MoaT-Link
configuration subtree for one server.  Spawns / cancels per-entry
workers as entries appear or change.
"""

from __future__ import annotations

import anyio
import logging

from moat.util import combine_dict
from moat.lib.path import Path
from moat.lib.xknx import XKNX
from moat.lib.xknx.io import ConnectionConfig, ConnectionType
from moat.lib.xknx.telegram import GroupAddress

from .model import KnxEntry, KnxServer
from .worker import run_in, run_out

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.link.client import LinkSender

    from collections.abc import Mapping

logger = logging.getLogger(__name__)


async def task(
    link: LinkSender,
    cfg: Mapping,
    server_name: str,
    *,
    local_ip: str | None = None,
    initial: bool = False,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the KNX connector for one gateway.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.knx`` configuration section.
        server_name: the server entry name inside the config subtree.
        local_ip: optional local IP override for the gateway connection.
        initial: if true, push existing outgoing states / pull inputs on
            startup.
        task_status: task-status for ``tg.start``.
    """
    prefix = Path.build(cfg["prefix"])
    server_path = prefix / server_name

    server_data = await link.d_get(server_path)
    if not isinstance(server_data, dict):
        server_data = {}
    srv_cfg = combine_dict(
        server_data.get("server", {}),
        cfg.get("server_default", {}),
    )

    add: dict = {}
    if local_ip is not None:
        add["local_ip"] = local_ip

    ccfg = ConnectionConfig(
        connection_type=ConnectionType.TUNNELING,
        gateway_ip=srv_cfg["host"],
        gateway_port=srv_cfg.get("port", 3671),
        **add,
    )

    async with XKNX(connection_config=ccfg) as srv, anyio.create_task_group() as tg:
        workers: dict[Path, anyio.CancelScope] = {}

        def _cancel(p: Path) -> None:
            sc = workers.pop(p, None)
            if sc is not None:
                sc.cancel()

        async def _start(p: Path, entry: KnxEntry) -> None:
            _cancel(p)
            if not entry.is_complete():
                logger.warning("Incomplete entry at %s, skipping", p)
                return
            if len(p) != 3 or not all(isinstance(x, int) for x in p):
                logger.warning("Entry %s is not at a 3-element group address", p)
                return
            main, middle, sub = (int(p[0]), int(p[1]), int(p[2]))
            addr = GroupAddress((main << 11) | (middle << 8) | sub)

            runner = run_in if entry.type_ == "in" else run_out

            async def _run(
                *,
                task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
            ) -> None:
                with anyio.CancelScope() as sc:
                    workers[p] = sc
                    task_status.started()
                    try:
                        await runner(link, srv, entry, addr, p, initial=initial)
                    except Exception:
                        logger.exception("Worker for %s failed", p)

            await tg.start(_run)

        async with link.d_watch(
            server_path,
            subtree=True,
            mark=True,
            cls=KnxServer,
        ) as mon:
            task_status.started()

            async for msg in mon:
                if msg is None:
                    continue
                p, _data = msg
                if not p:
                    continue

                node = mon.nodes.get(p)
                if isinstance(node, KnxEntry):
                    if node.is_complete():
                        await _start(p, node)
                    else:
                        _cancel(p)
                else:
                    _cancel(p)

        tg.cancel_scope.cancel()
