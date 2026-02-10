"""
Poll code
"""

from __future__ import annotations

import anyio
import logging
from functools import partial

from moat.util import attrdict, merge, to_attrdict
from moat.modbus.client import ModbusClient
from moat.modbus.server import create_server

from .device import ClientDevice, ServerDevice, fixup

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import Link

logger = logging.getLogger(__name__)


async def dev_poll(cfg: dict, link: Link, *, task_status=anyio.TASK_STATUS_IGNORED):
    """
    Run a device task on this set of devices, as configured by the config.

    The config will be preprocessed by `moat.modbus.dev.device.fixup`; the
    result will be returned via @task_status after setup is complete.
    """
    sl = cfg.setdefault("slots", attrdict())
    sl.setdefault("write", attrdict())
    sl._apply_default = True  # pylint:disable=protected-access  # noqa: SLF001
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
            from .device import Register as Reg  # pylint: disable=import-outside-toplevel  # noqa:PLC0415,I001

            RegS = Reg
        else:
            # The MoaT-Link client must live longer than the taskgroup
            from .link import Register  # pylint: disable=import-outside-toplevel  # noqa:PLC0415,I001

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

            srv.add_ignored_unit(*s.get("ignored", ()))

        def do_attach(v, dev):
            p = v.get("server", None)
            if p is None:
                return
            if isinstance(p, int):
                s, u = servers[p // 1000], p % 1000
            else:
                s, u = servers[p[0]], p[1]

            # Get or create UnitContext for this unit
            # If the unit already exists (e.g., from server config), add to it
            # Otherwise create a new one
            # Note: forward parameter is recognized but true transparent forwarding
            # is not yet implemented (complex due to request splitting across
            # configured/unconfigured register boundaries)
            unit_ctx = s.units.get(u)

            if unit_ctx is None:
                from .server_unit import ServerUnitContext  # noqa: PLC0415

                unit_ctx = ServerUnitContext()
                s.add_unit(u, unit_ctx)

            # Recursively find all Register objects in the dev.data tree and add them to the unit
            # This ensures transformations are applied when serving
            # Only add if the register doesn't already exist (server registers take precedence)
            def add_registers(d):
                from .device import Register  # noqa: PLC0415

                if isinstance(d, Register):
                    # Check for register remapping via 'server' parameter in register config
                    srv_reg = d.data.get("server", d.register)

                    # If server: none, don't add this register
                    if srv_reg is None or (isinstance(srv_reg, str) and srv_reg.lower() == "none"):
                        return

                    # Use remapped register number if specified
                    register_num = srv_reg if isinstance(srv_reg, int) else d.register

                    # Check if this register already exists in the unit
                    try:
                        existing = unit_ctx.store[d.reg_type.key].get(register_num + 1)
                    except (KeyError, AttributeError):
                        existing = None

                    # Only add if it doesn't exist
                    if existing is None:
                        unit_ctx.add(d.reg_type, register_num, d)
                        # Track slot mapping for age-based refresh
                        # Map all registers this value occupies (for multi-register values)
                        if hasattr(d, "slot") and d.slot is not None:
                            reg_len = d.len if hasattr(d, "len") else 1
                            for offset in range(register_num, register_num + reg_len):
                                unit_ctx.add_mapping(offset, d.reg_type.key, d.slot)
                elif isinstance(d, dict):
                    for v in d.values():
                        add_registers(v)

            add_registers(dev.data)

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
            logger.info("Server running.")
        else:
            logger.error("Poll running, no server.")

        pass  # wait until all tasks are done
