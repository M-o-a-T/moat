"""
Device file handling and serving
"""

import logging
from functools import partial
from pathlib import Path as FSPath

import anyio
import asyncclick as click
from moat.util import attrdict, merge, to_attrdict, yload, yprint

from ..client import ModbusClient
from .device import Device, fixup
from .server import Server

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
    if "distkv" in obj.cfg:
        from distkv.client import open_client

        from .distkv import Register

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

    # pylint: disable=import-outside-toplevel
    if "distkv" in obj.cfg:
        from distkv.client import open_client

        from .distkv import Register

        dkv = await ctx.with_async_resource(open_client(**obj.cfg.distkv))
        # "Reg" is created in the taskgroup
    else:
        from .device import Register as Reg

        dkv = None

    async with ModbusClient() as cl, anyio.create_task_group() as tg:
        nd = 0

        def make_dev(v, Reg, **kw):
            kw = to_attrdict(kw)
            vs = v.setdefault("src", attrdict())
            merge(vs, kw, s, replace=False)
            vsl = v.setdefault("slots", attrdict())
            merge(vsl, sl, replace=False)

            logger.info("Starting %r", vs)
            dev = Device(client=cl, factory=Reg)
            dev.load(data=v)
            return dev

        async with anyio.create_task_group() as tg:
            if dkv is not None:
                # The DistKV client must live longer than the taskgroup
                Reg = partial(Register, dkv=dkv, tg=tg)  # noqa: F811
            servers = []
            for s in d.get("server", ()):
                servers.append(Server(*s))

            for h, hv in d.get("hosts", {}).items():
                for u, v in hv.items():
                    dev = make_dev(v, Reg, host=h, unit=u)
                    nd += 1
                    tg.start_soon(dev.poll)

                    us = v.get("server", None)
                    if us is not None:
                        srv = servers[us // 1000]
                        us %= 1000
                        srv.attach(us, dev)

            for h, hv in d.get("hostports", {}).items():
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

        if not nd:
            logger.error("No devices to poll found.")
