# command line interface

import asyncclick as click

from moat.util import yprint, attrdict, NotGiven, as_service, P, attr_args
from moat.kv.data import node_attr

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage Wago controllers.")
async def cli():
    """
    List Wago controllers, modify device handling …
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
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        obj.cfg.kv.wago.prefix + path, nchain=obj.meta, max_depth=4 - len(path)
    ):
        rr = res
        if r.path:
            for rp in r.path:
                rr = rr.setdefault(rp, {})
        rr["_"] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


@cli.command("list")
@click.argument("path", nargs=1)
@click.pass_obj
async def list_(obj, path):
    """List the next stage.
    """
    path = P(path)
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        obj.cfg.kv.wago.prefix + path, nchain=obj.meta, min_depth=1, max_depth=1
    ):
        print(r.path[-1], file=obj.stdout)


@cli.command("attr")
@attr_args
@click.argument("path", nargs=1)
@click.pass_obj
async def attr_(obj, path, vars_, eval_, path_):
    """Set/get/delete an attribute on a given Wago element.

    `--eval` without a value deletes the attribute.
    """
    path = P(path)
    res = await node_attr(obj, obj.cfg.kv.wago.prefix + path, vars_,eval_,path_)

    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("port")
@click.option("-m", "--mode", help="Port mode. Use '-' to disable.")
@click.option(
    "-a",
    "--attr",
    nargs=2,
    multiple=True,
    help="One attribute to set (NAME VALUE). May be used multiple times.",
)
@click.argument("path", nargs=1)
@click.pass_obj
async def port_(obj, path, mode, attr):
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
    cfg = obj.cfg.kv.wago
    path = P(path)
    if len(path) != 4:
        raise click.UsageError("Path must be 4 elements: server+type+card+port.")
    res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 1)
    val = res.get("value", attrdict())
    val_p = attrdict()

    if mode:
        attr = (("mode", mode),) + attr
    for k, v in attr:
        if k == "count":
            if v == "+":
                v = True
            elif v == "-":
                v = False
            elif v in "xX*":
                v = None
            else:
                raise click.UsageError("'count' wants one of + - X")
        elif k == "rest":
            if v == "+":
                v = True
            elif v == "-":
                v = False
            else:
                raise click.UsageError("'rest' wants one of + -")
        elif k in {"src", "dest", "state"} or "." in v or ":" in v:
            val_p[k] = v
            continue
        else:
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
        val[k] = v

    res = await node_attr(obj, cfg.prefix + path, val, {}, val_p, res=res)

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
    cfg = obj.cfg.kv.wago

    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(cfg.prefix, min_depth=1, max_depth=1):
            print(r.path[-1], file=obj.stdout)
        return
    elif len(name) > 1:
        raise click.UsageError("Only one server allowed")
    name = name[0]
    if host or port:
        if delete:
            raise click.UsageError("You can't delete and set at the same time.")
        value = dict()
        if host:
            value["server.host"] = host
        if port:
            if port == "-":
                value["server.port"] = NotGiven
            else:
                value["server.port"] = int(port)
    elif delete:
        res = await obj.client.delete_tree(cfg.prefix / name, nchain=obj.meta)
        if obj.meta:
            async for k in res:
                yprint(k, stream=obj.stdout)
        return
    else:
        res = await obj.client.get(cfg.prefix / name, nchain=obj.meta)
        if not obj.meta:
            res = res.value
        yprint(res, stream=obj.stdout)
        return

    res = await node_attr(obj, cfg.prefix / name, value, (),() )
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.argument("name", nargs=1)
@click.pass_obj
async def monitor(obj, name):
    """Stand-alone task to monitor a single contoller.
    """
    from .task import task
    from .model import WAGOroot

    server = await WAGOroot.as_handler(obj.client)
    await server.wait_loaded()

    async with as_service(obj) as srv:
        await task(obj.client, obj.cfg.kv.wago, server[name], srv)
