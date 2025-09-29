"""
Basic tool support

"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position
import sys
from contextlib import asynccontextmanager

import asyncclick as click

from moat.util import P, Path, load_subgroup, yprint
from moat.micro.cmd.tree.dir import Dispatch

log = logging.getLogger()


@load_subgroup(sub_pre="moat.bms")
@click.option("-b", "--bat", "--battery", type=P, help="Battery to talk to. Default:'std'")
@click.pass_obj
async def cli(obj, bat):
    """Battery Manager"""
    cfg = obj.cfg
    if not bat:
        try:
            bat = cfg.ems.battery.paths["std"]
        except KeyError:
            raise click.UsageError(
                "No default battery. Set config 'ems.battery.paths.std' or use '--batt'.",
            ) from None
    if len(bat) == 1:
        try:
            bat = cfg.ems.battery.paths["bat[0]"]
        except KeyError:
            p = P("ems.battery.paths") / bat[0]
            raise click.UsageError(f"Couldn't find path at {bat} / {p}") from None
        else:
            if not isinstance(bat, Path):
                raise click.UsageError(
                    "--battery: requires a path (directly or at 'ems.battery.paths')",
                )
    obj.bat = bat


@asynccontextmanager
async def _bat(obj):
    async with Dispatch(cfg, run=True) as dsp, dsp.sub_at(obj.bat) as bat:
        yield bat


@cli.group
@click.argument("cell", type=int)
@click.pass_obj
async def cell(obj, cell):
    obj.cell = cell


@cell.command
@click.pass_obj
async def state(obj):
    async with _bat(obj) as bat:
        c = bat.sub_at(obj.cell)
        p = await c.param()
        u = await c.u()
        t = await c.t()
        tb = await c.tb()
        res = dict(param=p, u=u, t=dict(cell=t, balancer=tb))
        yprint(res, stream=obj.stdout)


@cell.command
@click.pass_obj
async def cfg(obj):
    print("TODO", file=sys.stderr)
    async with _bat(obj) as bat:
        c = bat.sub_at(obj.cell)
        await c.foo()
