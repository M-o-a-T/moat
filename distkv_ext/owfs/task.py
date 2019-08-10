"""
OWFS task for DistKV
"""

import anyio
from asyncowfs import OWFS
from asyncowfs.event import DeviceEvent, DeviceLocated, DeviceNotFound, DeviceValue
from collections import Mapping

from distkv.util import combine_dict, NotGiven
from distkv_ext.owfs.model import OWFSroot

import logging
logger = logging.getLogger(__name__)

async def mon(client, ow, hd):
    """
    Monitor OWFS for changes.
    """
    async with ow.events as events:
        async for msg in events:
            logger.info("%s", msg)

            if isinstance(msg, DeviceEvent):
                dev = msg.device
                node = hd.allocate(dev.family, exists=True)
                vf = node.value_or({}, Mapping)
                node = node.allocate(dev.code, exists=True)
                v = node.value
                if v is NotGiven:
                    v = {}
                    await node.update(v)
                v = combine_dict(v,vf)

            if isinstance(msg, DeviceLocated):
                await node.with_device(msg.device)

            elif isinstance(msg, DeviceNotFound):
                await node.with_device(None)

            elif isinstance(msg, DeviceValue):
                # Set an entry's value, if warranted.
                # TODO select an attribute.
                try:
                    path = v['attr'][msg.attribute]['dest']
                except KeyError:
                    continue
                else:
                    logger.error("VALUE %s %s %s",path,msg.attribute,msg.value)
                    res = None
                    try:
                        res = await client.get(*path, nchain=2)
                    except SyntaxError:
                        pass
                    else:
                        if res.get('value',NotGiven) == msg.value:
                            continue
                    await client.set(*path, value=msg.value,
                            **({'chain': res.chain} if res is not None else {}))


async def task(client, cfg, server=None, evt=None):
    async with OWFS() as ow:
        hd = await OWFSroot.as_handler(client)
        await ow.add_task(mon, client, ow, hd)
        if server:
            s = combine_dict(server, cfg.owfs.server_default)
            await ow.add_server(**s)
        else:
            for s in cfg.owfs.server:
                s = combine_dict(s,cfg.owfs.server_default)
                await ow.add_server(**s)
        if evt is not None:
            await evt.set()
        while True:
            await anyio.sleep(99999)

    

