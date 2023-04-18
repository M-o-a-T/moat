#!/usr/bin/env python3

import importlib
import logging
import os
import sys
from contextlib import asynccontextmanager

import anyio
import asyncclick as click
from moat.util import (
    P,
    as_service,
    attr_args,
    attrdict,
    merge,
    packer,
    process_args,
    unpacker,
    yload,
    yprint,
)
from moat.util.main import load_subgroup

from .compat import TaskGroup
from .direct import DirectREPL
from .main import ABytes, NoPort, copy_over, get_link, get_link_serial, get_remote, get_serial
from .path import MoatDevPath, MoatFSPath
from .proto.multiplex import Multiplexer
from .proto.stack import RemoteError

logger = logging.getLogger(__name__)


def clean_cfg(cfg):
    # cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
    return cfg


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
        with open(config, "r") as f:
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
