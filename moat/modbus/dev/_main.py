import asyncclick as click

from moat.util import yload, yprint, attrdict
import anyio
from .device import fixup,Device
from .poll import poll
from ..client import ModbusClient
from contextlib import AsyncExitStack


@click.group()
def cli():
    """Modbus device polling"""
    pass

@cli.command()
@click.argument("path", type=click.File("r"))
def dump(path):
    """Dump a postprocessed file"""
    d = yload(path)
    d = fixup(d)
    yprint(d)

@cli.command()
@click.option("--host", "-h", help="host to bind to")
@click.option("--port", "-p", type=int, help="port to bind to")
@click.option("--unit", "-u", type=int, help="Modbus unit to poll")
@click.argument("path", nargs=1, type=click.File("r"))
@click.argument("slot", nargs=-1)
@click.pass_context
async def poll(ctx, host, port, unit, path, slot):
    """Poll a Modbus device and forward"""
    obj = ctx.obj

    d = yload(path, attr=True)
    d = fixup(d)
    s = d.setdefault("src", attrdict())
    s.setdefault("host",host)
    s.setdefault("port",port)
    s.setdefault("unit",unit)

    if "distkv" in obj.cfg:
        from distkv.client import open_client
        from .distkv import Register
        from functools import partial
        dkv = await ctx.with_async_resource(open_client(**obj.cfg.distkv))
        tg = await ctx.with_async_resource(anyio.create_task_group())
        Reg = partial(Register, dkv=dkv, tg=tg)
    else:
        from .device import Register as Reg
    cl = await ctx.with_async_resource(ModbusClient())

    dev = Device(client=cl, factory=Reg)
    dev.load(data=d)

    await dev.poll(set(slot))

    


