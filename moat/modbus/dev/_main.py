"""
Device file handling, with a basic multi-device client
"""

import logging
from functools import partial
from pathlib import Path as FSPath

import anyio
import asyncclick as click
from moat.util import attrdict, yload, yprint

from ..client import ModbusClient
from .device import Device, fixup
from .poll import dev_poll

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Modbus device polling"""
    pass


@cli.command()
@click.option("-r", "--raw", is_flag=True, help="don't postprocess")
@click.option("-R", "--no-refs", is_flag=True, help="don't process references")
@click.argument("path", type=click.Path("r"))
def dump(path, raw, no_refs):
    """Dump a postprocessed file"""
    path = FSPath(path)
    with path.open("r") as f:
        d = yload(f, attr=True)
    if not raw:
        d = fixup(d, do_refs=not no_refs, this_file=path)
    yprint(d)


@cli.command()
@click.option("--host", "-h", help="host to bind to")
@click.option("--port", "-p", type=int, help="port to bind to")
@click.option("--unit", "-u", type=int, help="Modbus unit to poll")
@click.argument("path", nargs=1, type=click.File("r"))
@click.argument("slot", nargs=-1)
@click.pass_context
async def poll1(ctx, host, port, unit, path, slot):
    """Poll a single Modbus device"""
    obj = ctx.obj

    d = yload(path, attr=True)
    d = fixup(d)
    s = d.setdefault("src", attrdict())
    s.setdefault("host", host)
    s.setdefault("port", port)
    s.setdefault("unit", unit)

    # pylint: disable=import-outside-toplevel
    if "kv" in obj.cfg:
        from moat.kv .client import open_client

        from .kv import Register

        mt_kv = await ctx.with_async_resource(open_client(**obj.cfg.kv))
        tg = await ctx.with_async_resource(anyio.create_task_group())
        Reg = partial(Register, mt_kv=mt_kv, tg=tg)
    else:
        from .device import Register as Reg

    cl = await ctx.with_async_resource(ModbusClient())

    dev = Device(client=cl, factory=Reg)
    dev.load(data=d)

    await dev.poll(set(slot))


@cli.command()
@click.argument("path", type=click.File("r"))
@click.pass_context
async def poll(ctx, path):
    """Poll Modbus devices as directed via YAML."""
    obj = ctx.obj

    cfg = yload(path, attr=True)

    if "kv" in obj.cfg:
        # pylint: disable=import-outside-toplevel
        from moat.kv.client import client_scope

        mt_kv = await client_scope(**obj.cfg.kv)
    else:
        mt_kv = None

    await dev_poll(cfg, mt_kv)
