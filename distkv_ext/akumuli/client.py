# command line interface

import asyncclick as click
from asyncakumuli import DS

from distkv.data import node_attr, data_get
from distkv.util import yprint, attrdict, NotGiven, as_service, P

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage Akumuli storage.")
async def cli():
    """
    List Akumuli storage, modify data handling …
    """
    pass


@cli.command("list")
@click.argument("path", nargs=1)
@click.pass_obj
async def list_(obj, path):
    """Emit the state as a YAML file."""
    path = P(path)
    await data_get(obj, obj.cfg.akumuli.prefix + path)


@cli.command("set")
@click.option("-m", "--mode", help="DS mode. Default: 'gauge'", default="gauge")
@click.option(
    "-a",
    "--attr",
    help="The attribute to fetch. Default: None, the value is used directly.",
    default=":",
)
@click.argument("path", nargs=1)
@click.argument("source", nargs=1)
@click.argument("series", nargs=1)
@click.argument("tags", nargs=-1)
@click.pass_obj
async def set_(obj, path, source, mode, attr, series, tags):
    """Set/delete part of a series.
    \b
    path: the name of this copy command. Unique path, non-empty.
    source: the element with the data. unique path, non-empty.
    series: the Akumuli series to write to.
    tags: any number of "name=value" Akumuli tags to use for the series.

    A series of '-' deletes.
    """
    path = P(path)
    attr = P(attr)
    source = P(source)
    mode = getattr(DS, mode)
    tagged = {}
    if series == "-":
        if tags:
            raise click.UsageError("You can't add tags when deleting")
        series = None
        await obj.client.delete(obj.cfg.akumuli.prefix + path)
        return

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
    res = await obj.client.set(obj.cfg.akumuli.prefix + path, val)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("attr")
@click.option("-v", "--value", help="New value of the attribute.")
@click.option("-e", "--eval", "eval_", is_flag=True, help="The value shall be evaluated.")
@click.option("-p", "--path", "path_", is_flag=True, help="The value is a path.")
@click.argument("path", nargs=1)
@click.argument("attr", nargs=1)
@click.pass_obj
async def attr_(obj, attr, value, path, eval_, path_):
    """Set/get/delete an attribute on a given akumuli element.

    `--eval` without a value deletes the attribute.
    """
    path = P(path)

    if path_ and eval_:
        raise click.UsageError("split and eval don't work together.")
    if value and not attr:
        raise click.UsageError("Values must have locations ('-a ATTR').")
    if path_:
        value = P(value)
    res = await node_attr(obj, obj.cfg.akumuli.prefix + path, P(attr), value, eval_=eval_)

    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("server")
@click.option("-h", "--host", help="Host name of this server.")
@click.option("-p", "--port", help="Port of this server.")
@click.option("-d", "--delete", is_flag=True, help="Delete this server.")
@click.argument("name", nargs=-1)
@click.pass_obj
async def server_(obj, name, host, port, delete):
    """
    Configure a server.

    No arguments: list them.
    """
    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(obj.cfg.akumuli.prefix, min_depth=1, max_depth=1):
            print(r.path[-1], file=obj.stdout)
        return
    elif len(name) > 1:
        raise click.UsageError("Only one server allowed")
    name = name[0]
    if host or port:
        if delete:
            raise click.UsageError("You can't delete and set at the same time.")
        value = attrdict()
        if host:
            value.host = host
        if port:
            if port == "-":
                value.port = NotGiven
            else:
                value.port = int(port)
    elif delete:
        res = await obj.client.delete_tree(obj.cfg.akumuli.prefix + name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    res = await node_attr(obj, obj.cfg.akumuli.prefix | name, ("server",), value)

    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.argument("name", nargs=1)
@click.pass_obj
async def monitor(obj, name):
    """Stand-alone task to monitor a single Akumuli tree"""
    from distkv_ext.akumuli.task import task
    from distkv_ext.akumuli.model import AkumuliRoot

    server = await AkumuliRoot.as_handler(obj.client)
    await server.wait_loaded()

    async with as_service(obj) as srv:
        await task(obj.client, obj.cfg.akumuli, server[name], srv)
