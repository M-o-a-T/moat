"""
command line interface thing for KWB pellet burner
"""

from __future__ import annotations

import anyio
import logging
from contextlib import nullcontext

import asyncclick as click

from moat.util import yload
from moat.modbus.dev.poll import dev_poll

logger = logging.getLogger()


async def lifeticker(dest):
    "Task to periodically update the lifeticker modbus var"
    t_out = dest.regs.ksm.modbus.lifetick
    t_in = dest.regs.ksm.modbus.commit_lifetick

    t_out.value = 0
    v_old = t_in.value
    n_old = 0

    while True:
        for n in range(1, 65535):
            t_out.value = n
            await anyio.sleep(45)

            if t_in.value != v_old:
                v_old = t_in.value
                n_old = 0
            elif n_old > 2:
                raise RuntimeError("No commit_lifetick change")
            else:
                n_old += 1


@click.command(short_help="Access the KWB modbus.")  # pylint: disable=undefined-variable
@click.option("-c", "--cfg", type=click.File("r"), help="Moat-Modbus configuration", required=True)
@click.option("-h", "--host", help="Host to access")
@click.option("-p", "--port", type=int, help="Port to access")
@click.option("-u", "--unit", type=int, help="Unit to access")
@click.pass_context
async def cli(ctx, cfg, host, port, unit):
    """
    This command starts a Modbus client that connects to a KWB EasyFire pellet burner.

    It will send Lifetick updates.

    By default this command talks to all hosts with a `regs.modbus.lifetick` register.
    (DO NOT set `regs.modbus.lifetick` to mirror from anywhere.)

    """

    cfg = yload(cfg, attr=True)

    obj = ctx.obj
    if "link" in obj.cfg:
        # pylint: disable=import-outside-toplevel
        from moat.link.client import Link

        ln_ctx = Link(opj.cfg.link)
    else:
        ln_ctx = nullcontext(None)

    n = 0

    def get_one(d, h):
        if h is None:
            yield from d.values()
        elif h in d:
            yield d[h]

    async with (
        anyio.create_task_group() as tg,
        ln_ctx as mt_ln,
    ):
        cfg = await tg.start(dev_poll, cfg, mt_ln)

        def proc(dest):
            try:
                dest.regs.ksm.modbus.lifetick  # noqa:B018 pylint: disable=pointless-statement
            except AttributeError:
                return
            tg.start_soon(lifeticker, dest)

            nonlocal n
            n += 1

        for h in get_one(cfg.get("hostports", {}), host):
            for p in get_one(h, port):
                for dest in get_one(p, unit):
                    proc(dest)

        if port is None or port == 502:
            for h in get_one(cfg.get("hosts", {}), host):
                for dest in get_one(h, unit):
                    proc(dest)

        if n:
            # found a KWB system. Possibly do some work here.
            pass  # will sleep here, because dev_poll and lifeticker continue to run

        else:
            # did not find a KWB system. Stop.
            tg.cancel_scope.cancel()

    raise RuntimeError("No matching servers found")
