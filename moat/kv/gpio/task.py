"""
GPIO task for MoaT-KV
"""

from __future__ import annotations

import anyio
import logging

import moat.lib.gpio as gpio

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import GPIOchip

logger = logging.getLogger(__name__)


async def task(chip: GPIOchip, evt=None):  # noqa:D103
    with gpio.open_chip(label=chip.name) as srv:
        try:
            async with anyio.create_task_group() as tg:
                chip.task_group = tg
                await chip.set_chip(srv)
                if evt is not None:
                    evt.set()

                await anyio.sleep_forever()
        finally:
            chip.task_group = None
