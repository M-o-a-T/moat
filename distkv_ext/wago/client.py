# command line interface

import sys
import asyncclick as click
from functools import partial
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


@cli.command("list")
@click.argument("path", nargs=-1)
@click.pass_obj
async def list_(obj, path):
    """Emit the current state as a YAML file.
    """
    res = {}
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")
    if len(path) > 2:
        path[2] = int(path[2])
    if len(path) > 3:
        path[3] = int(path[3])

    async for r in obj.client.get_tree(*obj.cfg.wago.prefix, *path, nchain=obj.meta, max_depth=4-len(path)):
        pl = len(path) + len(r.path)
        if r.path:
            rr = res
            for rp in r.path:
                rr = rr.setdefault(rp,{})
        else:
            rr['_'] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


@cli.command('attr')
@click.option("-a","--attr", multiple=True, help="Attribute to list or modify.")
@click.option("-v","--value",help="New value of the attribute.")
@click.option("-e", "--eval", "eval_", is_flag=True, help="The value shall be evaluated.")
@click.option("-V", "--eval-path", type=int,multiple=True, help="Eval this path element")
@click.argument("path", nargs=-1)
@click.pass_obj
async def attr_(obj, attr, value, eval_path, path, eval_):
    """Set/get/delete an attribute on a given Wago element.

    An evaluated '-' deletes the attribute.
    """
    await _attr(obj, attr, value, eval_path, path, eval_)

async def _attr(obj, attr, value, eval_path, path, eval_):
    eval_path.extend((3,4))
    if value and not attr:
        raise click.UsageError("Values must have locations ('-a ATTR').")
    res = await obj.client.get(*obj.cfg.wago.prefix, *path_eval(path, eval_path), nchain=obj.meta or (value is not None))
    try:
        val = res.value
    except AttributeError:
        res.chain = None
    if not attr:
        yprint(res if obj.meta else val, stream=obj.stdout)
        return
    if value is None:
        val = res_get(res, *attr)
        yprint(val, stream=obj.stdout)
        return
    if value == "-" and eval_:
        value = res_delete(res, *attr)
    else:
        if eval_:
            value = eval(value)
        value = res_update(res, *attr, value=value)
    res = await obj.client.set(*obj.cfg.wago.prefix, *path_eval(path, eval_path), value=value, nchain=obj.meta, chain=res.chain)
    if obj.meta:
        yprint(res, stream=obj.stdout)

@cli.command('server')
@click.option("-h","--host",help="Host name of this server.")
@click.option("-p","--port",help="Port of this server.")
@click.argument("name", nargs=1)
@click.pass_obj
async def server(obj, name, host, port):
    if host or port:
        value = attrdict()
        if host:
            value.host = host
        if port:
            if port == "-":
                value.port = NotGiven
            else:
                value.port = int(port)
    else:
        value = None
    await _attr(obj, ("server",), value, [], (name,), False)


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

