"""
GPIO task for DistKV
"""

import anyio
import asyncgpio

from distkv_ext.gpio.model import GPIOchip

import logging

logger = logging.getLogger(__name__)


async def task(chip: GPIOchip, evt=None):
    with asyncgpio.open_chip(label=chip.name) as srv:
        try:
            async with anyio.create_task_group() as tg:
                chip.task_group = tg
                await chip.set_chip(srv)
                if evt is not None:
                    await evt.set()

                while True:
                    await anyio.sleep(99999)
        finally:
            chip.task_group = None
