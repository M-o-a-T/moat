# command line interface
from __future__ import annotations

import asyncclick as click

from moat.kv.server import Server


@click.command(short_help="Run the MoaT-KV server.")  # pylint: disable=undefined-variable
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
    hidden=True,
)
@click.option(
    "-i",
    "--incremental",
    default=None,
    help="Save incremental changes, not the complete state",
    hidden=True,
)
@click.option(
    "-I",
    "--init",
    default=None,
    help="Initial value to set the root to. Use only when setting up "
    "a cluster for the first time!",
    hidden=True,
)
@click.option(
    "-e",
    "--eval",
    "eval_",
    is_flag=True,
    help="The 'init' value shall be evaluated.",
    hidden=True,
)
@click.option(
    "-a",
    "--auth",
    "--authoritative",
    is_flag=True,
    help="Data in this file is complete: mark anything missing as known even if not.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Force 'successful' startup even if data are missing.",
)
@click.argument("name", nargs=1)
@click.argument("nodes", nargs=-1)
@click.pass_obj
async def cli(obj, name, load, save, init, incremental, eval_, auth, force, nodes):
    """
    This command starts a MoaT-KV server.

    One server in your network needs either an initial datum, or a copy of
    a previously-saved MoaT-KV state. Otherwise, no client connections will
    be accepted until synchronization with the other servers in your MoaT-KV
    network is complete.

    This command requires a unique NAME argument. The name identifies this
    server on the network. Never start two servers with the same name!

    You can force the server to fetch its data from a specific node, in
    case some data are corrupted. (This should never be necessary.)
    """

    kw = {}
    if eval_:
        kw["init"] = eval(init)  # pylint: disable=eval-used
    elif init == "-":
        kw["init"] = None
    elif init is not None:
        kw["init"] = init

    from moat.util import as_service

    if load and nodes:
        raise click.UsageError("Either read from a file or fetch from a node. Not both.")
    if auth and force:
        raise click.UsageError("Using both '-a' and '-f' is redundant. Choose one.")

    async with as_service(obj) as evt:
        s = Server(name, cfg=obj.cfg["kv"], **kw)
        if load is not None:
            await s.load(path=load, local=True, authoritative=auth)
        if nodes:
            await s.fetch_data(nodes, authoritative=auth)

        await s.serve(log_path=save, log_inc=incremental, force=force, ready_evt=evt)
