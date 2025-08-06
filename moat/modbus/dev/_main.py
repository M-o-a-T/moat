"""
Device file handling, with a basic multi-device client
"""

from __future__ import annotations

import logging
from pathlib import Path as FSPath

import asyncclick as click
from moat.util import yload, yprint

from .device import fixup
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

    if "link" in obj.cfg:
        # pylint: disable=import-outside-toplevel
        from moat.link.client import Link

        ln_ctx = Link(opj.cfg.link)
    else:
        ln_ctx = nullcontext(None)

    async with ln_ctx as mt_ln:
        await dev_poll(cfg, link=mt_ln)
