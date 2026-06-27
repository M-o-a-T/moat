"""
Main supervisor task for the Wago connector.

Connects to a single Wago controller and monitors the MoaT-Link
configuration subtree for one server.  Spawns / cancels per-port
workers as entries appear or change.
"""

from __future__ import annotations

import anyio
import logging

import asyncwago as wago

from moat.util import combine_dict
from moat.lib.path import Path
from moat.link.meta import MsgMeta

from .model import WagoPort, WagoRoot, WagoServer
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
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the Wago connector for one controller.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.wago`` configuration section.
        server_name: the server entry name inside the config subtree.
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

    try:
        async with wago.open_server(**srv_cfg) as srv:
            r = await srv.describe()

            # Build a local node tree and mark discovered ports present.
            root = WagoRoot()
            srv_node = root.add_child(server_name)
            for type_name, cards in r.items():
                type_node = srv_node.add_child(type_name)
                for card_num, port_count in cards.items():
                    card_node = type_node.add_child(card_num)
                    for port_num in range(1, port_count + 1):
                        port_node = card_node.add_child(port_num)
                        meta = MsgMeta(origin="discover", t=anyio.current_time())
                        port_node.set_(Path(), {"present": True}, meta)

            # Update server-level settings.
            poll = cfg.get("poll")
            if poll is not None:
                await srv.set_freq(poll)
            ping = cfg.get("ping")
            if ping is not None:
                await srv.set_ping_freq(ping)

            async with anyio.create_task_group() as tg:
                workers: dict[Path, anyio.CancelScope] = {}

                def _cancel(p: Path) -> None:
                    sc = workers.pop(p, None)
                    if sc is not None:
                        sc.cancel()

                async def _start(p: Path, entry: WagoPort) -> None:
                    _cancel(p)
                    if not entry.is_complete():
                        logger.warning("Incomplete entry at %s, skipping", p)
                        return
                    if len(p) != 3:
                        logger.warning("Entry %s is not at a 3-element port path", p)
                        return
                    card, port_num = int(p[1]), int(p[2])
                    type_name = str(p[0])

                    runner = run_in if type_name == "input" else run_out

                    async def _run(
                        *,
                        task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
                    ) -> None:
                        with anyio.CancelScope() as sc:
                            workers[p] = sc
                            task_status.started()
                            try:
                                await runner(link, srv, entry, card, port_num, p)
                            except Exception:
                                logger.exception("Worker for %s failed", p)
                            finally:
                                if workers.get(p) is sc:
                                    del workers[p]

                    await tg.start(_run)

                async with link.d_watch(
                    server_path,
                    subtree=True,
                    mark=True,
                    cls=WagoServer,
                ) as mon:
                    task_status.started()

                    async for msg in mon:
                        if msg is None:
                            continue
                        p, _data = msg
                        if not p:
                            continue

                        node = mon.nodes.get(p)
                        if isinstance(node, WagoPort):
                            if node.is_complete():
                                await _start(p, node)
                            else:
                                _cancel(p)
                        else:
                            _cancel(p)

            tg.cancel_scope.cancel()
    except TimeoutError:
        raise
    except OSError as exc:
        raise RuntimeError(
            f"Cannot connect to {srv_cfg.get('host')}:{srv_cfg.get('port')}"
        ) from exc
