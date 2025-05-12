"""
This module describes the MoaT data link.
"""

from __future__ import annotations

import anyio

# pylint: disable=missing-module-docstring
import logging
import sys
from functools import partial
from pathlib import Path as FSPath
import time

import asyncclick as click

from mqttproto import MQTTException

from moat.util import NotGiven, P, Path, load_subgroup, yprint
from moat.util.path import set_root

from .backend import RawMessage, get_backend
from .client import Link

try:
    from mqttproto import MQTTPublishPacket
except ImportError:
    MQTTPublishPacket = NotGiven


logger = logging.getLogger(__name__)

usage1 = """
"moat link" requires configuration. It should look like this:

    link:
        backend:
            driver: mqtt
            host: localhost
            port: 1883
            user: foo
            pass: bar
            codec: std-cbor
        root: !P moat.something-unique

The MQTT hierarchy below the "root" topic, with slashes instead of dots,
*must* be empty when you start a new installation.

Please add this stanza to the file "/etc/moat/moat.cfg" (or "/etc/moat.cfg",
or "~/.config/moat.cfg") and try again.
"""

usage2 = """
"moat link" requires a root topic.

This entry should be tagged with '!P' and be some dot-separated names.
For clarity it should start with 'moat.', though that's just a
recommendation.

Your MQTT server cannot contain any retained topics under that name
(when replacing the dots with slashes) when you start a new installation.

Config example:

    link:
        backend:
            …
        prefix: !P moat.com.your-domain

"""

usage9 = """

"moat link" requires at least one history server for stable operation.

Please run "sudo systemctl start moat-link-server", or
start "moat link server" in a separate terminal, and try again.
"""


@load_subgroup(sub_pre="moat.link.cmd", sub_post="cli", ext_pre="moat.link", ext_post="_main.cli")
@click.option("-n","--name", type=str, help="Name of this client (or server)")
@click.option("-p","--port", type=str, help="Port to use and/or connect to")
@click.pass_context
async def cli(ctx,name,port):
    """
    MoaT's data link

    This collection of commands is useful for managing and building MoaT itself.
    """
    obj = ctx.obj
    cfg = obj.cfg
    obj.name = name
    obj.port = port

    if "link" not in cfg or "backend" not in cfg["link"]:
        sys.stderr.write(usage1)
        raise click.UsageError("not configured")
    cfg = cfg["link"]
    if not isinstance(cfg.root, Path) or cfg.root == P("XXX.NotConfigured.YZ"):
        sys.stderr.write(usage2)
        raise click.UsageError("badly configured")


@cli.command("test")
@click.pass_obj
async def test(obj):
    "Test"

    lock = anyio.Lock()
    cfg = obj.cfg.link
    set_root(cfg)
    async def check_root():
        try:
            with anyio.fail_after(1) as sc:
                async with back.monitor(cfg.root) as mon:
                    async for msg in mon:
                        async with lock:
                            print("# Retained root dataset:")
                            yprint(msg.data)
                            print("---")
                            return
        except TimeoutError:
            print(f"## No retained root dataset on {cfg.root}.")

    async def check_server():
        try:
            with anyio.fail_after(1) as sc:
                async with back.monitor(P(":R.run.service.main.conn")) as mon:
                    async for msg in mon:
                        async with lock:
                            print("# Server link:")
                            yprint(msg.data)
                            print("---")
                            return
        except TimeoutError:
            print(f"### No server link on {cfg.root}!")


    async with get_backend(cfg) as back,back.connect(), anyio.create_task_group() as tg:
        tg.start_soon(check_root)
        tg.start_soon(check_server)
        

