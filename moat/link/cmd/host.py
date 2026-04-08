# command line interface  # noqa: D100
from __future__ import annotations

import anyio
import logging
from contextlib import nullcontext
from platform import uname

import asyncclick as click

from moat.util import NotGiven, as_service, attrdict, srepr
from moat.lib.broadcast import Broadcaster
from moat.lib.path import P
from moat.lib.run import AliasedGroup
from moat.link.announce import announcing
from moat.link.client import Link
from moat.link.host import HostList, ServiceMon

logger = logging.getLogger(__name__)


@click.group(cls=AliasedGroup, short_help="Manage host services.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    Each server that's connected to moat-link should run a host service.

    This command manages that service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if ctx.invoked_subcommand != "run":
        obj.conn = await ctx.with_async_resource(Link(cfg, common=True))


@cli.command()
@click.option("-m", "--main", is_flag=True, help="Main server flag (override)")
@click.option("-n", "--no-main", is_flag=True, help="Main server verbose no-action mode")
@click.option("-d", "--debug", is_flag=True, help="Debug?")
@click.pass_obj
async def run(obj, main, no_main, debug):
    """
    Host management background task.

    "moat link host run" should run on each MoaT-Link connected host.

    It provides keepalive-style ping messages and related services.
    """

    cfg = obj.cfg.link
    if not main:
        main = cfg.main == uname().node
    async with (
        Link(cfg) as link,
        as_service(attrdict(debug=debug, link=link)) as srv,
        announcing(link, host=not main, via=srv.evt, force=True),  # TODO: add service
        ServiceMon(cfg=cfg, link=link, debug=debug, fake=no_main)
        if main or no_main
        else nullcontext(),
    ):
        srv.started()
        await anyio.sleep_forever()


@cli.command()
@click.option("-t", "--timeout", type=float, help="Stop after this many seconds.")
@click.option("-d", "--dump", is_flag=True, help="Show details.")
@click.pass_obj
async def list(obj, timeout, dump):  # noqa: A001
    """
    Host list.

    "moat link host list" shows the hosts that are currently active.

    Output consists of three space-delimited columns:
    * connection's key
    * host name
    * service path

    The host name is empty if the service path starts with it.
    """

    hc = dict()
    with nullcontext() if timeout is None else anyio.move_on_after(timeout):
        async with HostList(link=obj.conn, cfg=obj.cfg.link, broadcaster=Broadcaster(10000)) as mq:
            async for h in mq:
                if dump:
                    print("    UPD  ", h.id, h.state.name, srepr(h.data, bare=True))
                else:
                    try:
                        up = h.data.p["up"]
                    except AttributeError:
                        up = None
                    for k, v in h.data.h.items():
                        ok = up if up is not None else v.get("up", False)
                        if hc.get(k, None) is ok:
                            continue
                        hc[k] = ok
                        print(
                            h.id,
                            ""
                            if "i" not in h.data or (len(k) and k[0] == h.data.i["host"])
                            else h.data.i["host"],
                            k,
                            "" if ok else "** DOWN **",
                        )


@cli.command()
@click.argument("paths", type=P, nargs=-1)
@click.pass_obj
async def kill(obj, paths):
    """
    Kill a hosted service.
    """

    link = obj.conn
    for p in paths:
        if len(p) == 1 and isinstance(p[0], str) and p[0].startswith("_"):
            await link.send(P(":R.run.ping.id") + p, NotGiven, retain=True)
        else:
            await link.send(P(":R.run.host") + p, NotGiven, retain=True)
