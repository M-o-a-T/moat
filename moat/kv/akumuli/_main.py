# command line interface
from __future__ import annotations

import logging

import asyncclick as click
from asyncakumuli import DS

from moat.util import NotGiven, P, attr_args, attrdict, yprint
from moat.kv.data import data_get, node_attr
from moat.kv.obj.command import std_command
from moat.link.announce import as_service

from .model import AkumuliRoot

logger = logging.getLogger(__name__)


async def _prepare_cli(obj):
    obj.data = await AkumuliRoot.as_handler(obj.client)


cli = std_command(
    click,
    name="server",
    sub_base=None,
    sub_name=NotGiven,
    id_name=None,
    prepare=_prepare_cli,
    aux=(
        click.option("-h", "--host", help="Host name of this server.", type=str),
        click.option("-p", "--port", help="Port of this server.", type=int),
        click.option("-t", "--topic", help="Raw MQTT topic for ad-hoc logging.", type=P),
    ),
)


@cli.command("dump")
@click.option("-l", "--one-line", is_flag=True, help="single line per entry")
@click.pass_obj
async def dump_(obj, one_line):
    """Emit a server's (sub)state as a list / YAML file."""
    if not one_line:
        await data_get(obj.client, obj.server._path, recursive=True, out=obj.stdout)  # noqa:SLF001
        return
    for n in obj.server.all_children:
        if n is obj.server:
            continue
        print(n, file=obj.stdout)


@cli.group("at", invoke_without_command=True, short_help="create/show/delete an entry")
@click.argument("path", nargs=1, type=P)
@click.pass_context
async def at_cli(ctx, path):
    obj = ctx.obj
    if len(path) == 0 or None in path:
        raise click.UsageError("Path cannot be empty or contain 'None'")
    obj.subpath = path
    obj.node = obj.server.follow(path)
    if ctx.invoked_subcommand is None:
        await data_get(obj.client, obj.server._path + obj.subpath, recursive=False, out=obj.stdout)  # noqa:SLF001


@at_cli.command("--help", hidden=True)
@click.pass_context
def help(ctx):
    print(at_cli.get_help(ctx))


@at_cli.command("dump")
@click.pass_obj
@click.option("-l", "--one-line", is_flag=True, help="single line per entry")
async def dump_at(obj, one_line):
    """Emit a subtree as a list / YAML file."""
    if one_line:
        await data_get(obj.client, obj.server._path + obj.subpath, recursive=True, out=obj.stdout)  # noqa:SLF001
        return
    for n in obj.node.all_children:
        print(n, file=obj.stdout)


@at_cli.command("add", short_help="Add an entry")
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry?")
@click.option("-m", "--mode", help="DS mode. Default: 'gauge'", default="gauge")
@click.option(
    "-a",
    "--attr",
    help="The attribute to fetch. Default: the stored value is used directly.",
    default=":",
    type=P,
)
@click.argument("source", nargs=1, type=P)
@click.argument("series", nargs=1)
@click.argument("tags", nargs=-1)
@click.pass_obj
async def add_(obj, source, mode, attr, series, tags, force):
    """Add a series to Akumuli.
    \b
    path: the name of this copy command. Unique path, non-empty.
    source: the element with the data. unique path, non-empty.
    series: the Akumuli series to write to.
    tags: any number of "name=value" Akumuli tags to use for the series.
    """

    if not force and obj.node.chain is not None:
        raise click.UsageError("This node already exists. Use '--force' or 'set'.")
    source = P(source)
    mode = getattr(DS, mode)
    tagged = {}

    if not tags:
        raise click.UsageError("You can't write to a series without tags")
    for x in tags:
        try:
            k, v = x.split("=", 2)
        except ValueError:
            raise click.UsageError("Tags must be key=value") from None
        tagged[k] = v

    val = dict(source=source, series=series, tags=tagged, mode=mode.name)
    if attr:
        val["attr"] = attr
    try:
        res = (await obj.client.get(source)).value
        if attr:
            res = attrdict._get(res, attr)  # noqa:SLF001
        if not isinstance(res, (int, float)):
            raise TypeError(res)
    except (AttributeError, KeyError):
        raise click.UsageError(f"The value at {source} does not exist.") from None
    except TypeError:
        raise click.UsageError(f"The value at {source} is not a number.") from None

    res = await obj.client.set(obj.server._path + obj.subpath, val)  # noqa:SLF001
    if obj.meta:
        yprint(res, stream=obj.stdout)


@at_cli.command("delete")
@click.pass_obj
async def delete_(obj):
    """Remove a series from Akumuli's copying.

    \b
    path: the name of the series. Unique path, non-empty.

    The data set is not physically deleted (with Akumuli that's
    impossible), but no new copying will happen.
    """
    res = await obj.client.delete(obj.server._path + obj.subpath, nchain=obj.meta or 1)  # noqa:SLF001
    if not res.chain:
        raise click.UsageError("This entry doesn't exist.")
    if obj.meta:
        yprint(res, stream=obj.stdout)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def attr_(obj, **kw):
    """Modify a given akumuli series (copier)."""
    if all(x not in kw for x in "vars_ eval_ path_".split):
        return

    res = await node_attr(obj, obj.server._path + obj.subpath, **kw)  # noqa:SLF001
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
@click.argument("paths", nargs=-1, type=P)
async def monitor(obj, paths):
    """Stand-alone task to monitor a single Akumuli tree"""
    from .model import AkumuliRoot  # noqa: PLC0415
    from .task import task  # noqa: PLC0415

    server = await AkumuliRoot.as_handler(obj.client)
    await server.wait_loaded()

    async with as_service(obj) as srv:
        await task(
            obj.client,
            obj.cfg.kv.akumuli,
            server[obj.server._name],  # noqa:SLF001
            evt=srv,
            paths=paths,
        )
