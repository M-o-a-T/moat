import asyncclick as click

from moat.util import yload, yprint, attrdict, merge, to_attrdict
import anyio
from .device import fixup,Device
from .poll import poll
from ..client import ModbusClient
from contextlib import AsyncExitStack
from functools import partial

import logging
logger = logging.getLogger(__name__)

@click.group()
def cli():
    """Modbus device polling"""
    pass

@cli.command()
@click.argument("path", type=click.File("r"))
def dump(path):
    """Dump a postprocessed file"""
    d = yload(path, attr=True)
    d = fixup(d)
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

    
@cli.command()
@click.argument("path", type=click.File("r"))
@click.pass_context
async def poll(ctx, path):
    """Poll Modbus devices as directed via YAML."""
    obj = ctx.obj

    d = yload(path, attr=True)
    d = fixup(d)

    s = d.setdefault("src", attrdict())
    sl = d.setdefault("slots", attrdict())

    if "distkv" in obj.cfg:
        from distkv.client import open_client
        from .distkv import Register
        from functools import partial
        dkv = await ctx.with_async_resource(open_client(**obj.cfg.distkv))
        #tg = await ctx.with_async_resource(anyio.create_task_group())
        #Reg = partial(Register, dkv=dkv, tg=tg)
    else:
        from .device import Register as Reg

    async with ModbusClient() as cl, anyio.create_task_group() as tg:
        nd = 0
        async def poll(v, **kw):
            kw = to_attrdict(kw)
            vs = v.setdefault("src", attrdict())
            merge(vs,kw,s, replace=False)
            vsl = v.setdefault("slots", attrdict())
            merge(vsl,sl, replace=False)

            logger.info("Starting %r", vs)
            dev = Device(client=cl, factory=Reg)
            dev.load(data=v)
            await dev.poll()

        async with anyio.create_task_group() as tg:
            for h,hv in d.get("hosts",{}).items():
                for u,v in hv.items():
                    Reg = partial(Register, dkv=dkv, tg=tg)
                    tg.start_soon(partial(poll, v, host=h, unit=u))
                    nd += 1
        
            for h,hv in d.get("hostports",{}).items():
                for p,pv in hv.items():
                    if not isinstance(p,int):
                        continue
                    for u,v in pv.items():
                        tg.start_soon(partial(poll(v, host=h, port=p, unit=u)))
                        nd += 1

        if not nd:
            logger.error("No devices to poll found.")

        


