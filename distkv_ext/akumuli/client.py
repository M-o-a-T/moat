# command line interface

import asyncclick as click
from asyncakumuli import DS

from distkv.data import node_attr, data_get
from distkv.util import yprint, attrdict, NotGiven, as_service, P, attr_args
from distkv.obj.command import std_command

from .model import AkumuliRoot

import logging

logger = logging.getLogger(__name__)


async def _prepare_cli(obj):
    obj.data = await AkumuliRoot.as_handler(obj.client)


cli = std_command(
    click,
    name="server",
    sub_base=None,
    sub_name=NotGiven,
    prepare=_prepare_cli,
    aux=(
        click.option("-h", "--host", help="Host name of this server.", type=str),
        click.option("-p", "--port", help="Port of this server.", type=int),
        click.option("-t", "--topic", help="Raw MQTT topic for ad-hoc logging.", type=P),
    ),
)

@cli.command("dump")
@click.option("-l","--one-line",is_flag=True,help="single line per entry")
@click.pass_obj
async def dump_(obj,one_line):
    """Emit a server's (sub)state as a list / YAML file."""
    if not one_line:
        await data_get(obj, obj.server._path, recursive=True)
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
        await data_get(obj, obj.server._path+obj.subpath, recursive=False)

@at_cli.command("--help", hidden=True)
@click.pass_context
def help(ctx):
    print(at_cli.get_help(ctx))

@at_cli.command("dump")
@click.pass_obj
@click.option("-l","--one-line",is_flag=True,help="single line per entry")
async def dump_at(obj,one_line):
    """Emit a subtree as a list / YAML file."""
    if one_line:
        await data_get(obj, obj.server._path+obj.subpath, recursive=True)
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
            res = attrdict._get(res, attr)
        if not isinstance(res,(int,float)):
            raise ValueError(res)
    except (AttributeError,KeyError):
        raise click.UsageError("The value at %s does not exist." % (source,)) from None
    except ValueError:
        raise click.UsageError("The value at %s is not a number." % (source,)) from None

    res = await obj.client.set(obj.server._path + obj.subpath, val)
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
    res = await obj.client.delete(obj.server._path + obj.subpath, nchain=obj.meta or 1)
    if not res.chain:
        raise click.UsageError("This entry doesn't exist.")
    if obj.meta:
        yprint(res, stream=obj.stdout)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def attr_(obj, vars_, eval_, path_):
    """Modify a given akumuli series (copier).
    """
    if not vars_ and not eval_ and not path_:
        return

    res = await node_attr(obj, obj.server._path + obj.subpath, vars_, eval_, path_)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
async def monitor(obj):
    """Stand-alone task to monitor a single Akumuli tree"""
    from distkv_ext.akumuli.task import task
    from distkv_ext.akumuli.model import AkumuliRoot

    server = await AkumuliRoot.as_handler(obj.client)
    await server.wait_loaded()

    async with as_service(obj) as srv:
        await task(obj.client, obj.cfg.akumuli, server[obj.server._name], srv)
