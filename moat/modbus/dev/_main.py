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
from .device import ClientDevice, fixup
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
