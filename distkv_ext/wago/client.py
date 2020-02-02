# command line interface

import sys
import asyncclick as click
from functools import partial
from collections.abc import Mapping

from distkv.exceptions import ClientError
from distkv.util import yprint, attrdict, combine_dict, data_get, NotGiven, path_eval
from distkv.util import res_delete, res_get, res_update

import logging

logger = logging.getLogger(__name__)

@main.group(short_help="Manage Wago controllers.")  # pylint: disable=undefined-variable
@click.pass_obj
async def cli(obj):
    """
    List Wago controllers, modify device handling …
    """
    pass


@cli.command()
@click.argument("path", nargs=-1)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file.
    """
    res = {}
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(*obj.cfg.wago.prefix, *path_eval(path, (3,4)), nchain=obj.meta, max_depth=4-len(path)):
        pl = len(path) + len(r.path)
        rr = res
        if r.path:
            for rp in r.path:
                rr = rr.setdefault(rp,{})
        rr['_'] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


@cli.command()
@click.argument("path", nargs=-1)
@click.pass_obj
async def list(obj, path):
    """List the next stage.
    """
    res = {}
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(*obj.cfg.wago.prefix, *path_eval(path, (3,4)), nchain=obj.meta, min_depth=1, max_depth=1):
        print(r.path[-1], file=obj.stdout)


@cli.command('attr')
@click.option("-a","--attr", multiple=True, help="Attribute to list or modify.")
@click.option("-v","--value",help="New value of the attribute.")
@click.option("-e", "--eval", "eval_", is_flag=True, help="The value shall be evaluated.")
@click.argument("path", nargs=-1)
@click.pass_obj
async def attr_(obj, attr, value, path, eval_):
    """Set/get/delete an attribute on a given Wago element.

    An evaluated '-' deletes the attribute.
    """
    if value and not attr:
        raise click.UsageError("Values must have locations ('-a ATTR').")
    await _attr(obj, attr, value, path, eval_)

@cli.command()
@click.option("-m", "--mode", help="Port mode. Use '-' to disable.")
@click.option("-a", "--attr", nargs=2, multiple=True, help="One attribute to set (NAME VALUE)")
@click.argument("path", nargs=-1)
@click.pass_obj
async def port(obj, path, mode, attr):
    """Set/get/delete port settings. This is a shortcut for the "attr" command.

    An evaluated '-' deletes the attribute.

    Known attributes for modes:
      input:
        read: dest (path)
        count: + interval (float), count (+-x for up/down/both)
      output:
        write: src (path), state (path)
        oneshot: + t_on (float), rest (+-), state (path)
        pulse:   + t_off (float)

    Paths elements are separated by spaces.
    "rest" is the state of the wire when the input is False.
    Floats may be paths, in which case they're read from there when starting.
    """
    if len(path) != 4:
        raise click.UsageError("Path must be 4 elements: server+type+card+port.")
    res = await obj.client.get(*obj.cfg.wago.prefix, *path_eval(path, (3,4)), nchain=obj.meta or 1)
    val = res.get('value', attrdict())

    if mode:
        attr = (('mode', mode),) + attr
    for k,v in attr:
        if v == '-':
            val.pop(k,None)
        elif k == "count":
            if v == '+':
                v = True
            elif v == '-':
                v = False
            elif v in 'xX*':
                v = None
        elif k == "rest":
            if v == '+':
                v = True
            elif v == '-':
                v = False
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

    await _attr(obj, (), val, path, True, res)

async def _attr(obj, attr, value, path, eval_, res=None):
    # Sub-attr setter.
    # Special: if eval_ is True, a value of '-' deletes. A mapping replaces instead of updating.
    if res is None:
        res = await obj.client.get(*obj.cfg.wago.prefix, *path_eval(path, (3,4)), nchain=obj.meta or (value is not None))
    try:
        val = res.value
    except AttributeError:
        res.chain = None
    if eval_:
        if value == "-":
            value = res_delete(res, *attr)
        elif isinstance(value, Mapping):
            # replace
            value = res_delete(res, *attr)
            value = value._update(*attr, value=value)
        else:
            value = res_update(res, *attr, value=value)
    else:
        if value is None:
            if not attr and obj.meta:
                val = res
            else:
                val = res_get(res, *attr)
            yprint(val, stream=obj.stdout)
            return
        value = res_update(res, *attr, value=value)
    res = await obj.client.set(*obj.cfg.wago.prefix, *path_eval(path, (3,4)), value=value, nchain=obj.meta, chain=res.chain)
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
        async for r in obj.client.get_tree(*obj.cfg.wago.prefix, min_depth=1, max_depth=1):
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
        res = await obj.client.delete_tree(*obj.cfg.wago.prefix, name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    await _attr(obj, ("server",), value, (name,), False)


@cli.command()
@click.argument("name", nargs=1)
@click.pass_obj
async def monitor(obj, name):
    """Stand-alone task to monitor a single contoller.
    """
    from distkv_ext.wago.task import task
    from distkv_ext.wago.model import WAGOroot
    server = await WAGOroot.as_handler(obj.client)
    await server.wait_loaded()
    await task(obj.client, obj.cfg.wago, server[name], None)

