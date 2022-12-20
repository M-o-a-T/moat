"""
Poll code
"""

import logging
from functools import partial

import anyio
from moat.util import attrdict, merge, to_attrdict

from ..client import ModbusClient
from .device import Device, fixup
from .server import Server

logger = logging.getLogger(__name__)


async def dev_poll(cfg, dkv, *, task_status=None):
    """
    Run a device task on this set of devices, as configured by the config.

    The config will be preprocessed by `moat.modbus.dev.device.fixup`; the
    result will be returned via @task_status after setup is complete.
    """
    cfg = fixup(cfg)

    s = cfg.setdefault("src", attrdict())
    sl = cfg.setdefault("slots", attrdict())

    async with ModbusClient() as cl, anyio.create_task_group() as tg:
        nd = 0

        async def make_dev(v, Reg, **kw):
            kw = to_attrdict(kw)
            vs = v.setdefault("src", attrdict())
            merge(vs, kw, replace=False)
            vsl = v.setdefault("slots", attrdict())
            merge(vsl, sl, replace=False)

            logger.info("Starting %r", vs)

            dev = Device(client=cl, factory=Reg)
            dev.load(data=v)

            return scope.spawn_service(dev.as_scope)

        async with anyio.create_task_group() as tg:
            if dkv is None:
                from .device import Register as Reg  # pylint: disable=import-outside-toplevel
            else:
                # The DistKV client must live longer than the taskgroup
                from .distkv import Register  # pylint: disable=import-outside-toplevel

                Reg = partial(Register, dkv=dkv, tg=tg)  # noqa: F811

            servers = []
            for s in cfg.get("server", ()):
                servers.append(Server(**s))

            for h, hv in cfg.get("hosts", {}).items():
                for u, v in hv.items():
                    dev = make_dev(v, Reg, host=h, unit=u)
                    nd += 1
                    tg.start_soon(dev.poll)

                    us = v.get("server", None)
                    if us is not None:
                        srv = servers[us // 1000]
                        us %= 1000
                        srv.attach(us, dev)

            for h, hv in cfg.get("hostports", {}).items():
                for p, pv in hv.items():
                    if not isinstance(p, int):
                        continue
                    for u, v in pv.items():
                        dev = make_dev(v, Reg, host=h, port=p, unit=u)
                        tg.start_soon(dev.poll)
                        nd += 1

                        us = v.get("server", None)
                        if us is not None:
                            srv = servers[us // 1000]
                            us %= 1000
                            srv.attach(us, dev)

            for s in servers:
                tg.start_soon(s.run)

            if task_status is not None:
                task_status.started(cfg)

        if not nd:
            logger.error("No devices to poll found.")
