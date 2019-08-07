"""
OWFS task for DistKV
"""

import anyio
from asyncowfs import OWFS
from asyncowfs.event import DeviceEvent, DeviceLocated, DeviceNotFound

from distkv.util import combine_dict, NotGiven
from distkv_ext.owfs.model import OWFSroot

import logging
logger = logging.getLogger(__name__)

async def mon(ow, hd):
    async with ow.events as events:
        async for msg in events:
            logger.info("%s", msg)

            if isinstance(msg, DeviceEvent):
                dev = msg.device
                node = hd.follow(dev.family, dev.code, create=True)

                v = node.value
                if v is NotGiven:
                    v = {}
                    await node.update(v)

            if isinstance(msg, DeviceLocated):
                await node.with_device(msg.device)

            elif isinstance(msg, DeviceNotFound):
                await node.with_device(None)


async def task(client, cfg, evt=None):
    async with OWFS() as ow:
        hd = await OWFSroot.as_handler(client)
        await ow.add_task(mon, ow, hd)
        for s in cfg.owfs.server:
            s = combine_dict(s,cfg.owfs.server_default)
            await ow.add_server(**s)
            if evt is not None:
                await evt.set()
            while True:
                await anyio.sleep(99999)

    

