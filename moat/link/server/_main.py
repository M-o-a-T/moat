# command line interface
from __future__ import annotations

import asyncclick as click

import anyio
from moat.kv.server import Server
from moat.util import as_service


@click.command(short_help="Run the MoaT-Link data server.")  # pylint: disable=undefined-variable
@click.option(
    "-l",
    "--load",
    type=click.Path(readable=True, exists=True, allow_dash=False),
    default=None,
    help="Event log to preload.",
)
@click.option(
    "-s",
    "--save",
    type=click.Path(writable=True, allow_dash=False),
    default=None,
    help="Event log to write to.",
)
@click.option(
    "-i",
    "--incremental",
    default=None,
    help="Log incremental changes, not the complete state",
)
@click.option(
    "-I",
    "--init",
    default=None,
    help="Initial value to set the root to. Do not use this option unless"
    "setting up a new cluster!",
)
@click.argument("name", nargs=1)
@click.argument("nodes", nargs=-1)
@click.pass_obj
async def cli(obj, name, load, save, incremental, init):
    """
    Start a MoaT-Link server. It defaults to connecting to the local MQTT
    broker.

    One server in your network needs either an initial datum, or a copy of
    a previously-saved MoaT-Link state. Otherwise, no client connections will
    be accepted until synchronization with the other servers in your MoaT-Link
    network is complete.

    This command requires a unique NAME argument. The name identifies this
    server on the network. Never start two servers with the same name!
    """

    kw = {}
    if init == "-":
        kw["init"] = None
    elif init is not None:
        kw["init"] = init

    async with as_service(obj) as evt:
        s = Server(name, cfg=obj.cfg["kv"], **kw)

        async with anyio.create_task_group() as tg:
            await tg.start(s.serve)
            evt.set()

