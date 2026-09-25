# command line interface
from __future__ import annotations

import anyio

import asyncclick as click

from moat.util import as_service
from moat.link.client import Link
from moat.link.server import Server


@click.command(short_help="Run the MoaT-Link data server.")  # pylint: disable=undefined-variable
@click.option("-n", "--name", type=str, help="Name of this server (default: hostname)")
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
    "-L",
    "--local",
    "force_local",
    is_flag=True,
    help="Don't compete for master status. Implies local-only operation.\n"
    'Same as configuring "local_only: yes"; cannot be overridden by config.',
)
@click.option(
    "-I",
    "--init",
    default=None,
    help="Initial value to set the root to. Do not use this option unless "
    "setting up a new cluster!",
)
@click.pass_obj
async def cli(obj, load, save, init, force_local, name):
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

    With --local (-L) the server participates in normal operation (sending
    ping messages) but refrains from claiming responsibility: its heartbeat
    remains quiet so it will neither be elected nor considered eligible.
    This mirrors the config setting ``moat.link.server.local_only``.
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

    if name is None:
        import platform  # noqa: PLC0415

        name = platform.node()

    if force_local:
        # Flag beats config. Writing it into the (already defaulted) ``link``
        # subtree keeps every consumer consistent; ``forced_local`` is the
        # untouchable belt-and-braces twin.
        scf = obj.cfg.link.setdefault("server", {})
        scf["local_only"] = True

    async with as_service(obj) as evt:
        s = Server(cfg=obj.cfg.link, name=name, forced_local=force_local, **kw)
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

        async with (
            Link(obj.cfg.link) as li,
            li.announcing(force=True) as ann,
        ):
            if ann is not None:
                ann.set()

            await s.wait_stopped()
