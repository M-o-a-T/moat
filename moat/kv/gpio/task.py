"""
GPIO task for MoaT-KV
"""

from __future__ import annotations

import anyio
import moat.lib.gpio as gpio


import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import GPIOchip

logger = logging.getLogger(__name__)


async def task(chip: GPIOchip, evt=None):
    with gpio.open_chip(label=chip.name) as srv:
        try:
            async with anyio.create_task_group() as tg:
                chip.task_group = tg
                await chip.set_chip(srv)
                if evt is not None:
                    evt.set()

                while True:
                    await anyio.sleep(99999)
        finally:
            chip.task_group = None
