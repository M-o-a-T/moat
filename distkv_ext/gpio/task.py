"""
GPIO task for DistKV
"""

import anyio
import asyncgpio
import socket
try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from distkv.util import combine_dict, NotGiven, attrdict
from distkv.exceptions import ClientConnectionError
from distkv_ext.gpio.model import GPIOroot, GPIOchip

import logging
logger = logging.getLogger(__name__)

async def task(client, cfg, chip: GPIOchip, evt=None):
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

