"""
Main supervisor task for the GPIO connector.

Opens a GPIO chip and monitors the MoaT-Link configuration subtree for
one host/chip.  Spawns / cancels per-line workers as entries appear or
change.
"""

from __future__ import annotations

import anyio
import logging

import moat.lib.gpio as gpio
from moat.util import combine_dict
from moat.lib.path import Path

from .model import GpioChip, GpioLine
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
    host_name: str,
    chip_name: str,
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the GPIO connector for one chip.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.gpio`` configuration section.
        host_name: the host entry name.
        chip_name: the chip entry name inside the host subtree.
        task_status: task-status for ``tg.start``.
    """
    prefix = Path.build(cfg["prefix"])
    chip_path = prefix / host_name / chip_name

    chip_data = await link.d_get(chip_path)
    if not isinstance(chip_data, dict):
        chip_data = {}

    with gpio.open_chip(label=chip_name) as chip:
        async with anyio.create_task_group() as tg:
            workers: dict[Path, anyio.CancelScope] = {}

            def _cancel(p: Path) -> None:
                sc = workers.pop(p, None)
                if sc is not None:
                    sc.cancel()

            async def _start(p: Path, entry: GpioLine) -> None:
                _cancel(p)
                if not entry.is_complete():
                    logger.warning("Incomplete entry at %s, skipping", p)
                    return
                if len(p) != 1 or not isinstance(p[0], int):
                    logger.warning("Entry %s is not a single integer line number", p)
                    return
                line_num = int(p[0])

                runner = run_in if entry.type_ == "input" else run_out
                line_cfg = combine_dict(
                    entry.data_ if isinstance(entry.data_, dict) else {},
                    dict(cfg),
                )

                async def _run(
                    *,
                    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
                ) -> None:
                    with anyio.CancelScope() as sc:
                        workers[p] = sc
                        task_status.started()
                        try:
                            await runner(link, chip, entry, line_num, p, line_cfg)
                        except Exception:
                            logger.exception("Worker for %s failed", p)
                        finally:
                            if workers.get(p) is sc:
                                del workers[p]

                await tg.start(_run)

            async with link.d_watch(
                chip_path,
                subtree=True,
                mark=True,
                cls=GpioChip,
            ) as mon:
                task_status.started()

                async for msg in mon:
                    if msg is None:
                        continue
                    p, _data = msg
                    if not p:
                        continue

                    node = mon.nodes.get(p)
                    if isinstance(node, GpioLine):
                        if node.is_complete():
                            await _start(p, node)
                        else:
                            _cancel(p)
                    else:
                        _cancel(p)

            tg.cancel_scope.cancel()
