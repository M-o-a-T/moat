"""
Command-line interface for moat.link.akumuli.
"""

from __future__ import annotations

import logging

import asyncclick as click
from asyncakumuli import DS

from moat.util import NotGiven
from moat.lib.path import P
from moat.link._data import data_get
from moat.link.client import Link

logger = logging.getLogger(__name__)


@click.group(short_help="Manage Akumuli series.")
@click.pass_context
async def cli(ctx):
    """Configure Akumuli time-series forwarding.

    Series entries live below the configured ``link.akumuli.prefix``
    path, grouped by server name.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    obj.akumuli_cfg = obj.cfg.link.akumuli
    obj.prefix = obj.akumuli_cfg.prefix


@cli.command("list")
@click.argument("server", type=str)
@click.pass_obj
async def list_(obj, server):
    """List series entries for a server."""
    path = obj.prefix + P(server)
    await data_get(obj.conn, path, recursive=True, out=obj.stdout)


@cli.command("show")
@click.argument("server", type=str)
@click.argument("name", type=P)
@click.pass_obj
async def show_(obj, server, name):
    """Show a single series entry."""
    path = obj.prefix + P(server) + name
    await data_get(obj.conn, path, recursive=False, out=obj.stdout)


@cli.command("add")
@click.argument("server", type=str)
@click.argument("name", type=P)
@click.argument("source", type=P)
@click.argument("series", type=str)
@click.argument("tags", nargs=-1)
@click.option("-m", "--mode", default="gauge", help="DS mode (default: gauge).")
@click.option(
    "-a",
    "--attr",
    default=None,
    type=P,
    help="Attribute path to extract from the source value.",
)
@click.option("-f", "--force", is_flag=True, help="Overwrite existing entry.")
@click.pass_obj
async def add_(obj, server, name, source, series, tags, mode, attr, force):
    """Add a series entry.

    \\b
    SERVER: server name.
    NAME:   unique entry name (path).
    SOURCE: MoaT-Link path of the value to watch.
    SERIES: Akumuli series name.
    TAGS:   key=value pairs for Akumuli tags.
    """
    path = obj.prefix + P(server) + name
    mode = getattr(DS, mode, None)
    if mode is None:
        raise click.UsageError("Unknown mode")
    if not tags:
        raise click.UsageError("At least one tag is required")

    tagged = {}
    for t in tags:
        try:
            k, v = t.split("=", 1)
        except ValueError:
            raise click.UsageError("Tags must be key=value") from None
        tagged[k] = v

    if not force:
        try:
            await obj.conn.d_get(path)
        except (KeyError, ValueError):
            pass
        else:
            raise click.UsageError("Entry exists. Use --force to overwrite.")

    val: dict = {"source": source, "series": series, "tags": tagged, "mode": mode.name}
    if attr:
        val["attr"] = attr
    await obj.conn.d_set(path, val)


@cli.command("delete")
@click.argument("server", type=str)
@click.argument("name", type=P)
@click.pass_obj
async def delete_(obj, server, name):
    """Remove a series entry."""
    path = obj.prefix + P(server) + name
    await obj.conn.d_set(path, NotGiven)


@cli.command("monitor")
@click.argument("server", type=str)
@click.pass_obj
async def monitor_(obj, server):
    """Run the Akumuli connector for one server."""
    from .task import task  # noqa:PLC0415

    await task(obj.conn, obj.akumuli_cfg, server)
