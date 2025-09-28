"""
Battery management main code
"""

from __future__ import annotations

import logging

import asyncclick as click

from moat.util import merge, yload, yprint
from moat.micro.main import get_link  # pylint: disable=E0401,E0611
from moat.micro.proto.stack import RemoteError  # pylint: disable=E0401,E0611
from moat.util.main import load_subgroup

logger = logging.getLogger(__name__)


@load_subgroup(prefix="moat.ems.battery")
@click.pass_obj
@click.option(
    "-c",
    "--config",
    help="Configuration file (YAML)",
    type=click.Path(dir_okay=False, readable=True),
)
async def cli(obj, config):
    """Battery subsystem"""
    cfg = obj.cfg.moat.ems.battery

    if config:
        with open(config) as f:
            cc = yload(f)
            merge(cfg, cc)


@cli.command()
@click.pass_obj
@click.option("-a", "--app", help="Battery app")
async def state(obj, app):
    """
    Get battery status.
    """
    if app is None:
        for k, v in obj.cfg.apps.items():
            if ".battery." not in v:
                continue
            if app is None:
                app = k
            else:
                raise click.UsageError("Multiple battery apps in config. Specify one.")
        if app is None:
            raise click.UsageError("No battery app in config")

    async with get_link(obj) as req:
        try:
            res = await req.send(["loc", app, "state"])
        except RemoteError as err:
            yprint(dict(e=str(err.args[0])))
        else:
            yprint(res)
