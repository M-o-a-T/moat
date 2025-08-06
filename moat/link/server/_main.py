# command line interface
from __future__ import annotations

import asyncclick as click

import anyio
from moat.link.server import Server
from moat.util import as_service


@click.command(short_help="Run the MoaT-Link data server.")  # pylint: disable=undefined-variable
@click.option(
    "-l",
    "--load",
    type=click.Path(readable=True, exists=True, allow_dash=False),
    default=None,
    help="Initial data to preload.",
)
@click.option(
    "-s",
    "--save",
    type=click.Path(writable=True, allow_dash=False),
    default=None,
    help="Save a data snapshot after startup.",
)
@click.option(
    "-I",
    "--init",
    default=None,
    help="Initial value to set the root to. Do not use this option unless "
    "setting up a new cluster!",
)
@click.pass_obj
async def cli(obj, load, save, init):
    """
    Start a MoaT-Link server. It defaults to connecting to the local MQTT
    broker.

    One server in your network needs either an initial datum, or a copy of
    a previously-saved MoaT-Link state. Otherwise, no client connections will
    be accepted until synchronization with the other servers in your MoaT-Link
    network is complete.

    This command requires a unique NAME argument ("moat link -n NAME server …").
    The name identifies this server on the network. Never start two servers
    with the same name!
    """

    kw = {}
    if init == "-":
        kw["init"] = None
    elif init is not None:
        kw["init"] = init
    if load:
        kw["load"] = load
    if save:
        kw["save"] = save

    if obj.name is None:
        raise click.UsageError("You need to specify a name ('moat link -n NAME server').")

    async with as_service(obj) as evt:
        s = Server(cfg=obj.cfg.link, name=obj.name, **kw)
        ev = anyio.Event()

        async def mon(ev):
            try:
                with anyio.fail_after(3):
                    await ev.wait()
            except TimeoutError:
                print("… waiting for sync …")
                await ev.wait()

        if obj.debug:
            evt.tg.start_soon(mon, ev)
        await evt.tg.start(s.serve)
        evt.set()
        ev.set()
        await anyio.sleep_forever()
