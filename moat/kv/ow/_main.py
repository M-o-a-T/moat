# command line interface
from __future__ import annotations

import asyncclick as click
from moat.util import (
    yprint,
    attrdict,
    NotGiven,
    P,
    Path,
    as_service,
    attr_args,
    ensure_cfg,
)
from moat.kv.data import data_get, node_attr
from .model import OWFSroot

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage 1wire devices.")
@click.pass_obj
async def cli(obj):
    """
    List Onewire devices, modify device handling …
    """
    obj.data = await OWFSroot.as_handler(obj.client)
    ensure_cfg("moat.kv.ow", obj.cfg)


@cli.command("list")
@click.option("-d", "--device", help="Device to access.")
@click.option("-f", "--family", help="Device family to modify.")
@click.pass_obj
async def list_(obj, device, family):
    """Emit the current state as a YAML file."""
    if device is not None and family is not None:
        raise click.UsageError("Family and device code can't both be used")

    prefix = obj.cfg.kv.ow.prefix
    if family:
        f = int(family, 16)
        path = Path(f)

        def pm(p):
            if len(p) < 1:
                return path
            return Path(f"{f:02x}.{p[0]:12x}", *p[1:])

    elif device:
        f, d = device.split(".", 2)[0:2]
        path = Path(int(f, 16), int(d, 16))

        def pm(p):
            return Path(device) + p

    else:
        path = Path()

        def pm(p):
            if len(p) == 0:
                return p
            elif not isinstance(p[0], int):
                return None
            elif len(p) == 1:
                return Path("%02x" % p[0])
            else:
                return Path(f"{p[0]:02x}.{p[1]:12x}") + p[2:]

    if obj.meta:

        def pm(p):
            return Path(str(prefix + path)) + p

    await data_get(obj.client, prefix + path, as_dict="_", path_mangle=pm, out=obj.stdout)


@cli.command("attr", help="Mirror a device attribute to/from MoaT-KV")
@click.option("-d", "--device", help="Device to access.")
@click.option("-f", "--family", help="Device family to modify.")
@click.option("-i", "--interval", type=float, help="read value every N seconds")
@click.option("-w", "--write", is_flag=True, help="Write to the device")
@click.option("-a", "--attr", "attr_", help="The node's attribute to use", default=":")
@click.argument("attr", nargs=1)
@click.argument("path", nargs=1)
@click.pass_obj
async def attr__(obj, device, family, write, attr, interval, path, attr_):
    """Show/add/modify an entry to repeatedly read an 1wire device's attribute.

    You can only set an interval, not a path, on family codes.
    A path of '-' deletes the entry.
    If you set neither interval nor path, reports the current
    values.
    """
    path = P(path)
    prefix = obj.cfg.kv.ow.prefix
    if (device is not None) + (family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")
    if interval and write:
        raise click.UsageError("Writing isn't polled")

    remove = False
    if len(path) == 1 and path[0] == "-":
        path = ()
        remove = True

    if family:
        if path:
            raise click.UsageError("You cannot set a per-family path")
        fd = (int(family, 16),)
    else:
        f, d = device.split(".", 2)[0:2]
        fd = (int(f, 16), int(d, 16))

    attr = P(attr)
    attr_ = P(attr_)
    if remove:
        res = await obj.client.delete(prefix + fd + attr)
    else:
        val = dict()
        if path:
            val["src" if write else "dest"] = path
        if interval:
            val["interval"] = interval
        if len(attr_):
            val["src_attr" if write else "dest_attr"] = attr_

        res = await obj.client.set(prefix + fd + attr, value=val)

    if res is not None and obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("set")
@click.option("-d", "--device", help="Device to modify.")
@click.option("-f", "--family", help="Device family to modify.")
@attr_args
@click.argument("subpath", nargs=1, type=P, default=P(":"))
@click.pass_obj
async def set_(obj, device, family, subpath, **kw):
    """Set or delete some random attribute.

    For deletion, use '-e ATTR -'.
    """
    if (device is not None) + (family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")

    if family:
        fd = (int(family, 16),)
        if len(subpath):
            raise click.UsageError("You can't use a subpath here.")
    else:
        f, d = device.split(".", 2)[0:2]
        fd = (int(f, 16), int(d, 16))

    res = await node_attr(obj, obj.cfg.kv.ow.prefix + fd + subpath, **kw)
    if res and obj.meta:
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
    prefix = obj.cfg.kv.ow.prefix
    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(prefix | "server", min_depth=1, max_depth=1):
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
        res = await obj.client.delete_tree(prefix | "server" | name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    res = await node_attr(obj, prefix | "server" | name, ((P("server"), value),), (), ())
    if res and obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
@click.argument("server", nargs=-1)
async def monitor(obj, server):
    """Stand-alone task to monitor one or more OWFS servers."""
    from .task import task

    async with as_service(obj) as srv:
        await task(obj.client, obj.cfg.kv, server, srv)
