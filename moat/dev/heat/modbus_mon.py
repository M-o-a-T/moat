"""
Babysitter for the Solvis Modbus poller (HEAT.md §3.10).

Port of the legacy ``run_solvis_mon``: run ``moat modbus dev poll`` for
the Solvis shim and restart it whenever the Solvis reports error code 26
(which the poller doesn't recover from by itself).
"""

from __future__ import annotations

import anyio
import logging
import subprocess
import sys

import asyncclick as click

from moat.lib.path import Path  # noqa: TC002  # pydantic needs it at runtime

from .config import UnitCfg

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.link.client import LinkSender

    from collections.abc import Callable, Sequence

__all__ = ["ModbusMonCfg", "cli", "run_modbus_mon"]

_logger = logging.getLogger(__name__)


class ModbusMonCfg(UnitCfg):
    """Configuration of the Modbus monitor."""

    err: Path | None = None
    """The Solvis error flag; its ``:1.code`` sub-item holds the error code.
    (Legacy ``misc.mon_solvis.err``, e.g. ``heat.s.control.errors``.)
    `None`: the monitor is not configured."""
    data: str = "/etc/moat/modbus.stiebelfake.yaml"
    """The poller's configuration file."""
    restart_code: int = 26
    """Error code that makes us restart the poller."""
    settle: float = 60
    """Don't react to errors for this long after starting, seconds."""
    pause: float = 3
    """Wait this long after stopping the poller before starting it again."""
    restart_timeout: float = 15
    """The restarted poller should be running within this time."""


def _command(cfg: ModbusMonCfg) -> list[str]:
    return ["moat", "modbus", "dev", "poll", cfg.data]


async def _open(cmd: Sequence[str]) -> Any:
    return await anyio.open_process(
        list(cmd), stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr
    )


async def run_modbus_mon(
    link: LinkSender,
    cfg: ModbusMonCfg,
    open_process: Callable[[Sequence[str]], Any] = _open,
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Run the poller and restart it on the configured error code, until cancelled.

    Args:
        link: The MoaT-Link client.
        cfg: The monitor's configuration.
        open_process: Starts the poller (``anyio.open_process``-like, an
            async context manager); for tests.
    """
    if cfg.err is None:
        raise ValueError("The Modbus monitor needs 'err' (the Solvis error path)")
    again = anyio.Event()
    running = anyio.Event()

    async def poller() -> None:
        nonlocal again, running
        while True:
            async with await open_process(_command(cfg)) as proc:
                try:
                    running.set()
                    await again.wait()
                finally:
                    proc.kill()
            await anyio.sleep(cfg.pause)

    async with anyio.create_task_group() as tg:
        tg.start_soon(poller)
        await running.wait()
        task_status.started()
        await anyio.sleep(cfg.settle)

        async with link.d_watch(cfg.err, state=False) as mon:
            async for flag in mon:
                if not flag:
                    continue
                try:
                    code = await link.d_get(cfg.err / 1 / "code")
                except KeyError:
                    code = None
                if code != cfg.restart_code:
                    _logger.error("Solvis error %r", code)
                    continue
                _logger.warning("Solvis error %r: restarting the Modbus poller", code)
                running = anyio.Event()
                again.set()
                again = anyio.Event()
                try:
                    with anyio.fail_after(cfg.restart_timeout):
                        await running.wait()
                except TimeoutError:
                    _logger.error("The Modbus poller did not restart")
                else:
                    _logger.info("Modbus poller restarted")


@click.command(short_help="Restart the Solvis Modbus poller when it gets stuck.")
@click.pass_obj
async def cli(obj: Any) -> None:
    """
    Run ``moat modbus dev poll`` for the Solvis shim and restart it on
    Solvis error 26. Configuration: ``cfg.app.heat.modbus_mon``.
    """
    from moat.link.client import Link  # noqa: PLC0415

    from .config import load_config  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        cfg = await load_config(link, "modbus_mon", ModbusMonCfg)
        await run_modbus_mon(link, cfg)
