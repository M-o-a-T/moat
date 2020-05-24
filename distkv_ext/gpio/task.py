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
    cfg = combine_dict(server.value_or({}, Mapping).get('server',{}), cfg['server_default'])

    with asyncgpio.open_chip(chip.name, **cfg) as srv:
        chip.task_group = tg
        try:
            async with anyio.open_task_group() as tg:
                await chip.set_chip(srv)
                if evt is not None:
                    await evt.set()

                while True:
                    await anyio.sleep(99999)
        finally:
            chip._tg = None

