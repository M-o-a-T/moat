"""
OWFS task for DistKV
"""

import anyio
from asyncowfs import OWFS
from asyncowfs.event import DeviceEvent, DeviceLocated, DeviceNotFound, DeviceValue
from collections.abc import Mapping

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
                fam = hd.allocate(dev.family, exists=True)
                vf = fam.value_or({}, Mapping)
                node = fam.allocate(dev.code, exists=True)
                v = node.value
                if v is NotGiven:
                    v = {}
                    await node.update(v)
                v = combine_dict(v,vf)
                print(msg)

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
                    logger.debug("VALUE %s %s %s",path,msg.attribute,msg.value)
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
        port = cfg.owfs.port
        if not server:
            si = hd.server.items()
        elif isinstance(server,str):
            si = ((server,hd.server[server]),)
        else:
            si = ((s,hd.server[s]) for s in server)
        for sname,s in si:
            s = combine_dict(s.server, {"port":port})
            await ow.add_server(name=sname, **s)
        if evt is not None:
            await evt.set()
        while True:
            await anyio.sleep(99999)

    

