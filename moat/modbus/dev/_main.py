"""
Device file handling, with a basic multi-device client
"""

from __future__ import annotations

import anyio
import logging
from contextlib import nullcontext
from functools import partial
from pathlib import Path as FSPath

import asyncclick as click

from moat.util import as_service, yload, yprint
from moat.lib.run import AliasedGroup

from .device import fixup
from .poll import dev_poll

logger = logging.getLogger(__name__)


@click.group(cls=AliasedGroup)
def cli() -> None:
    """Modbus device polling"""
    pass


@cli.command()
@click.option("-r", "--raw", is_flag=True, help="don't postprocess")
@click.option("-R", "--no-refs", is_flag=True, help="don't process references")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=FSPath))
def dump(path, raw, no_refs) -> None:
    """Dump a postprocessed file"""
    path = FSPath(path)
    with path.open("r") as f:
        d = yload(f, attr=True)
    if not raw:
        d = fixup(d, do_refs=not no_refs, this_file=path)
    yprint(d)


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=FSPath))
@click.pass_context
async def poll(ctx, path) -> None:
    """Poll Modbus devices as directed via YAML.

    Readiness is signalled to systemd as soon as the servers are running.
    """
    obj = ctx.obj

    with path.open("r") as f:
        cfg = yload(f, attr=True)

    if "link" in obj.cfg:
        # pylint: disable=import-outside-toplevel
        from moat.link.client import Link  # noqa: PLC0415

        ln_ctx = Link(obj.cfg.link)
    else:
        ln_ctx = nullcontext(None)

    async with ln_ctx as mt_ln, as_service(obj) as srv:
        await dev_poll (cfg, link=mt_ln, this_file=path, task_status=srv)
