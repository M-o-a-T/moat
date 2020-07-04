# command line interface

import sys
import asyncclick as click
from functools import partial
from collections.abc import Mapping

from distkv.command import node_attr
from distkv.exceptions import ClientError
from distkv.util import yprint, attrdict, combine_dict, data_get, NotGiven, path_eval
from distkv.util import as_service, P, data_get

import logging

logger = logging.getLogger(__name__)

@main.group(short_help="Manage Akumuli storage.")  # pylint: disable=undefined-variable
@click.pass_obj
async def cli(obj):
    """
    List Akumuli storage, modify data handling …
    """
    pass


@cli.command()
@click.argument("path", nargs=1)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file.
    """
    res = {}
    path = P(path)
    await data_get(obj.cfg.akumuli.prefix+path)


@cli.command()
@click.argument("path", nargs=1)
@click.pass_obj
async def list(obj, path):
    """List the next stage.
    """
    res = {}
    path = P(path)

    async for r in obj.client.get_tree(obj.cfg.akumuli.prefix+path, nchain=obj.meta, min_depth=1, max_depth=1):
        print(r.path[-1], file=obj.stdout)


@cli.command('attr')
@click.option("-a","--attr",help="Attribute to list or modify.", default=':')
@click.option("-v","--value",help="New value of the attribute.")
@click.option("-e", "--eval", "eval_", is_flag=True, help="The value shall be evaluated.")
@click.option("-p", "--path", "path_", is_flag=True, help="The value is a path.")
@click.argument("path", nargs=1)
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
    res = await node_attr(obj, obj.cfg.akumuli.prefix+path, P(attr), value, eval_=eval_)

    if obj.meta:
        yprint(res, stream=obj.stdout)

@cli.command()
@click.option("-m", "--mode", help="Port mode. Use '-' to disable.")
@click.option("-a", "--attr", nargs=2, multiple=True, help="One attribute to set (NAME VALUE). May be used multiple times.")
@click.argument("path", nargs=1)
@click.pass_obj
async def port(obj, path, mode, attr):
    """Set/get/delete port settings. This is a shortcut for the "attr" command.

    \b
    Known attributes for modes:
      input:
        read: dest (path)
        count: + interval (float), count (+-x for up/down/both)
      output:
        write: src (path), state (path)
        oneshot: + t_on (float), rest (+-), state (path)
        pulse:   + t_off (float)

    \b
    Paths elements are separated by spaces.
    "rest" is the state of the wire when the input is False.
    Floats may be paths, in which case they're read from there when starting.
    """
    oath = P(path)
    res = await obj.client.get(obj.cfg.akumuli.prefix+path, nchain=obj.meta or 1)
    val = res.get('value', attrdict())

    if mode:
        attr = (('mode', mode),) + attr
    for k,v in attr:
        if k == "count":
            if v == '+':
                v = True
            elif v == '-':
                v = False
            elif v in 'xX*':
                v = None
            else:
                raise click.UsageError("'count' wants one of + - X")
        elif k == "rest":
            if v == '+':
                v = True
            elif v == '-':
                v = False
            else:
                raise click.UsageError("'rest' wants one of + -")
        elif k in {"src", "dest"} or ' ' in v:
            v = v.split(' ')
            v = tuple(x for x in v if x != '')
        else:
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
        val[k] = v

    res = await node_attr(obj, obj.cfg.akumuli.prefix+path, (), val, eval_=False, res=res)

    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command('server')
@click.option("-h","--host",help="Host name of this server.")
@click.option("-p","--port",help="Port of this server.")
@click.option("-d","--delete",is_flag=True, help="Delete this server.")
@click.argument("name", nargs=-1)
@click.pass_obj
async def server(obj, name, host, port, delete):
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
        res = await obj.client.delete_tree(obj.cfg.akumuli.prefix+name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    res = await node_attr(obj, obj.cfg.akumuli.prefix|name, ("server",), value)

    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.argument("name", nargs=1)
@click.pass_obj
async def monitor(obj, name):
    """Stand-alone task to monitor a single contoller.
    """
    from distkv_ext.akumuli.task import task
    from distkv_ext.akumuli.model import AkumuliRoot
    server = await AKUMULIroot.as_handler(obj.client)
    await server.wait_loaded()

    async with as_service(obj) as srv:
        await task(obj.client, obj.cfg.akumuli, server[name], srv)

