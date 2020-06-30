# command line interface

import asyncclick as click
from distkv.util import yprint, attrdict, NotGiven, P
from distkv.command import node_attr

import logging

logger = logging.getLogger(__name__)


@main.group(short_help="Manage 1wire devices.")  # pylint: disable=undefined-variable
async def cli():
    """
    List Onewire devices, modify device handling …
    """
    pass


@cli.command("list")
@click.argument("path", nargs=1)
@click.pass_obj
async def list_(obj, path):
    """Emit the current state as a YAML file.
    """
    res = {}
    path = P(path)
    if len(path) > 2:
        raise click.UsageError("Only one or two path elements allowed")
    if len(path) == 2:
        if path[1] == "-":
            path = path[:-1]
        path = [int(x, 16) for x in path]
        res = await obj.client.get(obj.cfg.owfs.prefix + path, nchain=obj.meta)
        if not obj.meta:
            res = res.value

    else:
        path = [int(x, 16) for x in path]
        async for r in obj.client.get_tree(
            obj.cfg.owfs.prefix + path,
            nchain=obj.meta,
            min_depth=max(0, 1 - len(path)),
            max_depth=2 - len(path),
        ):

            if len(path) == 0:
                if len(r.path) and not isinstance(r.path[0], int):
                    continue
                if len(r.path) == 1:
                    f = "%02x" % (r.path[-1],)
                    c = "_"
                else:
                    f = "%02x" % (r.path[-2],)
                    c = "%012x" % (r.path[-1],)
                rr = res.setdefault(f, {})
                if not obj.meta:
                    r = r.value
                rr[c] = r
            else:
                if len(r.path) == 0:
                    c = "_"
                else:
                    c = "%012x" % (r.path[-1],)
                if not obj.meta:
                    r = r.value
                res[c] = r

    yprint(res, stream=obj.stdout)


@cli.command("attr", help="Mirror a device attribute to/from DistKV")
@click.option("-d", "--device", help="Device to access.")
@click.option("-f", "--family", help="Device family to modify.")
@click.option("-i", "--interval", type=float, help="read value every N seconds")
@click.option("-w", "--write", is_flag=True, help="Write to the device")
@click.argument("attr", nargs=1)
@click.argument("path", nargs=1)
@click.pass_obj
async def attr_(obj, device, family, write, attr, interval, path):
    """Show/add/modify an entry to repeatedly read an 1wire device's attribute.

    You can only set an interval, not a path, on family codes.
    A path of '-' deletes the entry.
    If you set neither interval nor path, reports the current
    values.
    """
    path = P(path)
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

    eval_ = False
    val = NotGiven
    if remove:
        eval_ = True
    else:
        val = dict()
        if path:
            val["src" if write else "dest"] = path
        if interval:
            val["interval"] = interval
        if not val:
            val = NotGiven

    res = await node_attr(obj, obj.cfg.owfs.prefix + fd, ("attr", attr,), value=val, eval_=eval_)
    if res is not None and obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("set")
@click.option("-d", "--device", help="Device to modify.")
@click.option("-f", "--family", help="Device family to modify.")
@click.option("-v", "--value", help="The attribute to set or delete")
@click.option("-e", "--eval", "eval_", is_flag=True, help="Whether to eval the value")
@click.option("-s", "--split", is_flag=True, help="Split the value into words")
@click.argument("name", nargs=1)
@click.pass_obj
async def set_(obj, device, family, value, eval_, name, split):
    """Set or delete some random attribute.

    For deletion, use '-ev-'.
    """
    name = P(name)
    if (device is not None) + (family is not None) != 1:
        raise click.UsageError("Either family or device code must be given")
    if not len(name):
        raise click.UsageError("You need to name the attribute")
    if eval_ and split:
        raise click.UsageError("Split and eval can't be used together")

    if family:
        fd = (int(family, 16),)
    else:
        f, d = device.split(".", 2)[0:2]
        fd = (int(f, 16), int(d, 16))

    if eval_ and value == "-":
        value = NotGiven

    res = await node_attr(
        obj, obj.cfg.owfs.prefix + fd, name, value=value, eval_=eval_, split_=split
    )
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
    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(
            obj.cfg.owfs.prefix | "server", min_depth=1, max_depth=1
        ):
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
        res = await obj.client.delete_tree(obj.cfg.owfs.prefix | "server" | name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    res = await node_attr(
        obj, obj.cfg.owfs.prefix | "server" | name, P("server"), value, eval_=False
    )
    if res and obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
@click.argument("server", nargs=-1)
async def monitor(obj, server):
    """Stand-alone task to monitor one or more OWFS servers.
    """
    from distkv_ext.owfs.task import task

    await task(obj.client, obj.cfg, server)
