"""
Poll code
"""

from __future__ import annotations

import logging
from functools import partial

import anyio
from asyncscope import scope
from moat.util import attrdict, merge, to_attrdict

from moat.modbus.client import ModbusClient
from .device import ServerDevice, ClientDevice, fixup
from moat.modbus.server import create_server

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from moat.link.client import Link

logger = logging.getLogger(__name__)


async def dev_poll(cfg:dict, link:Link, *, task_status=anyio.TASK_STATUS_IGNORED):
    """
    Run a device task on this set of devices, as configured by the config.

    The config will be preprocessed by `moat.modbus.dev.device.fixup`; the
    result will be returned via @task_status after setup is complete.
    """
    sl = cfg.setdefault("slots", attrdict())
    sl.setdefault("write", attrdict())
    sl._apply_default = True  # pylint:disable=protected-access
    cfg = fixup(cfg)

    s = cfg.setdefault("src", attrdict())
    sl = cfg.slots

    async with ModbusClient() as cl, anyio.create_task_group() as tg:
        nd = 0

        async def make_dev(v, Reg, **kw):
            kw = to_attrdict(kw)
            vs = v.setdefault("src", attrdict())
            merge(vs, kw, replace=False)
            vsl = v.setdefault("slots", attrdict())
            merge(vsl, sl, replace=False)

            logger.info("Starting %r", vs)

            dev = ClientDevice(client=cl, factory=Reg)
            await dev.load(data=v)

            # return await scope.spawn_service(dev.as_scope)
            async def task(dev, *, task_status):
                async with dev:
                    task_status.started(dev)
                    await anyio.sleep_forever()
            return await tg.start(task, dev)

        if link is None:
            from .device import Register as Reg  # pylint: disable=import-outside-toplevel

            RegS = Reg
        else:
            # The MoaT-Link client must live longer than the taskgroup
            from .link import Register  # pylint: disable=import-outside-toplevel

            Reg = partial(Register, link=link, tg=tg)
            RegS = partial(Register, link=link, tg=tg, is_server=True)

        # relay-out server(s)
        servers = []
        for s in cfg.get("server", ()):
            srv = create_server(s)
            servers.append(srv)

            for u, v in s.get("units", {}).items():
                dev = ServerDevice(factory=RegS)
                await dev.load(data=v)
                srv.add_unit(u, dev)
                nd += 1

        def do_attach(v, dev):
            p = v.get("server", None)
            if p is None:
                return
            if isinstance(p, int):
                s, u = servers[p // 1000], p % 1000
            else:
                s, u = servers[p[0]], p[1]
            s.add_unit(u, dev.unit)

            nonlocal nd
            nd += 1

        # serial clients
        for h, hv in cfg.get("ports", {}).items():
            try:
                sp = hv["serial"]
            except KeyError:
                logger.error("No serial params for port %r", h)
                continue
            for u, v in hv.items():
                if not isinstance(u, int):
                    continue
                dev = await make_dev(v, Reg, port=h, serial=sp, unit=u)
                tg.start_soon(dev.poll)
                do_attach(v, dev)

        # TCP clients
        for h, hv in cfg.get("hosts", {}).items():
            for u, v in hv.items():
                if not isinstance(u, int):
                    continue
                dev = await make_dev(v, Reg, host=h, unit=u)
                tg.start_soon(dev.poll)
                do_attach(v, dev)

        # more TCP clients
        for h, hv in cfg.get("hostports", {}).items():
            for p, pv in hv.items():
                if not isinstance(p, int):
                    continue
                for u, v in pv.items():
                    dev = await make_dev(v, Reg, host=h, port=p, unit=u)
                    tg.start_soon(dev.poll)
                    do_attach(v, dev)

        for s in servers:
            evt = anyio.Event()
            tg.start_soon(partial(s.serve, opened=evt))
            await evt.wait()

        task_status.started(cfg)

        if nd:
            logger.info("Running.")
        if not nd:
            logger.error("No devices to poll found.")

        pass  # wait until all tasks are done
