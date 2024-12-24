"""
OWFS task for DistKV
"""

from __future__ import annotations

import anyio
from asyncowfs import OWFS
from asyncowfs.event import (
    DeviceEvent,
    DeviceLocated,
    DeviceNotFound,
    DeviceValue,
    DeviceException,
)
from collections.abc import Mapping

from moat.util import combine_dict, NotGiven, Path
from .model import OWFSroot

import logging

logger = logging.getLogger(__name__)


async def mon(ow, hd):
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
                v = combine_dict(v, vf)

            if isinstance(msg, DeviceLocated):
                await node.with_device(msg.device)

            elif isinstance(msg, DeviceNotFound):
                await node.with_device(None)

            elif isinstance(msg, DeviceException):
                attr = msg.attribute
                if isinstance(msg.attribute, str):
                    attr = (attr,)
                await node.root.err.record_error(
                    "onewire",
                    Path.build(node.subpath) + attr,
                    exc=msg.exception,
                )

            elif isinstance(msg, DeviceValue):
                # Set an entry's value, if warranted.
                # TODO select an attribute.

                attr = msg.attribute
                if isinstance(msg.attribute, str):
                    attr = (attr,)
                node = node.follow(attr, create=False)
                await node.dest_value(msg.value)
                await node.root.err.record_working("onewire", Path.build(node.subpath) + attr)


async def task(client, cfg, server=None, evt=None):
    async with OWFS() as ow:
        hd = await OWFSroot.as_handler(client)
        await ow.add_task(mon, ow, hd)
        port = cfg.ow.port
        if not server:
            si = ((s._name, s) for s in hd.server)
        elif isinstance(server, str):
            si = ((server, hd.server[server]),)
        else:
            si = ((s, hd.server[s]) for s in server)
        for sname, s in si:
            s = combine_dict(s.server, {"port": port})
            await ow.add_server(name=sname, **s)
        if evt is not None:
            evt.set()
        while True:
            await anyio.sleep(99999)
