# command line interface

import asyncclick as click
from collections.abc import Mapping

from distkv.data import res_delete, res_get, res_update
from distkv.util import yprint, attrdict, NotGiven, as_service, P, Path, path_eval

from xknx.remote_value import RemoteValueSensor

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage KNX controllers.")
async def cli():
    """
    List KNX controllers, modify device handling …
    """
    pass


@cli.command()
@click.argument("path", nargs=1)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file."""
    res = {}
    path = P(path)
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        obj.cfg.knx.prefix + path, nchain=obj.meta, max_depth=4 - len(path)
    ):
        # pl = len(path) + len(r.path)
        rr = res
        if r.path:
            for rp in r.path:
                rr = rr.setdefault(rp, {})
        rr["_"] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


@cli.command(name="list")
@click.argument("path", nargs=1)
@click.pass_obj
async def list_(obj, path):
    """List the next stage."""
    path = P(path)
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        obj.cfg.knx.prefix + path, nchain=obj.meta, min_depth=1, max_depth=1, add_empty=True
    ):
        if not isinstance(r.path[-1], int):
            continue
        print(r.path[-1], file=obj.stdout)


@cli.command("attr")
@click.option("-a", "--attr", multiple=True, help="Attribute to list or modify.")
@click.option("-v", "--value", help="New value of the attribute.")
@click.option("-e", "--eval", "eval_", is_flag=True, help="The value shall be evaluated.")
@click.option("-s", "--split", is_flag=True, help="The value shall be word-split.")
@click.option("-p", "--path", "path_", is_flag=True, help="The value shall be path-split.")
@click.argument("bus", nargs=1)
@click.argument("group", nargs=1)
@click.pass_obj
async def attr_(obj, attr, value, bus, group, eval_, path_, split):
    """Set/get/delete an attribute on a given KNX element.

    `--eval` without a value deletes the attribute.
    """
    group = (int(x) for x in group.split("/")) if group else ()
    path = Path(bus, *group)
    if len(path) != 4:
        raise click.UsageError("Group address must be 3 /-separated elements.")

    if (split + eval_ + path_) > 1:
        raise click.UsageError("split and eval don't work together.")
    if value and not attr:
        raise click.UsageError("Values must have locations ('-a ATTR').")
    if split:
        value = value.split()
    elif path_:
        value = P(value)
    await _attr(obj, attr, value, path, eval_)


@cli.command(
    "addr",
    help=f"""\
Set/get/delete device settings. This is a shortcut for the "attr" command.

\b
Known attributes:
    type=in:
    mode (data type)
    dest (path)
    type=out:
    mode (data type)
    src (path)

\b
Paths elements are separated by spaces.

Known modes: {" ".join(RemoteValueSensor.DPTMAP.keys())}
""",
)
@click.option("-t", "--type", "typ", help="Must be 'in' or 'out'. Use '-' to delete.")
@click.option("-m", "--mode", help="Use '-' to disable.")
@click.option(
    "-a",
    "--attr",
    nargs=2,
    multiple=True,
    help="One attribute to set (NAME VALUE). May be used multiple times.",
)
@click.argument("bus", nargs=1)
@click.argument("group", nargs=1)
@click.pass_obj
async def addr(obj, bus, group, typ, mode, attr):
    """Set/get/delete device settings. This is a shortcut for the "attr" command."""
    group = (int(x) for x in group.split("/"))
    path = Path(bus, *group)
    if len(path) != 4:
        raise click.UsageError("Group address must be 3 /-separated elements.")
    res = await obj.client.get(obj.cfg.knx.prefix + path, nchain=obj.meta or 1)
    val = res.get("value", attrdict())

    if typ == "-":
        res = await obj.client.delete(obj.cfg.knx.prefix + path, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return

    if typ:
        attr = (("type", typ),) + attr
    if mode:
        attr = (("mode", mode),) + attr
    for k, v in attr:
        if k in {"src", "dest"}:
            v = P(v)
        else:
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
        val[k] = v

    await _attr(obj, (), val, path, False, res)


async def _attr(obj, attr, value, path, eval_, res=None):
    # Sub-attr setter.
    # Special: if eval_ is True, an empty value deletes. A mapping replaces instead of updating.
    if res is None:
        res = await obj.client.get(obj.cfg.knx.prefix + path, nchain=obj.meta or 1)
    try:
        val = res.value
    except AttributeError:
        res.chain = None
    if eval_:
        if value is None:
            value = res_delete(res, attr)
        else:
            value = path_eval(value)
            if isinstance(value, Mapping):
                # replace
                value = res_delete(res, attr)
                value = value._update(attr, value=value)
            else:
                value = res_update(res, attr, value=value)
    else:
        if value is None:
            if not attr and obj.meta:
                val = res
            else:
                val = res_get(res, attr)
            yprint(val, stream=obj.stdout)
            return
        value = res_update(res, attr, value=value)

    res = await obj.client.set(
        obj.cfg.knx.prefix + path, value=value, nchain=obj.meta, chain=res.chain
    )
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("server")
@click.option("-h", "--host", help="Host name of this server.")
@click.option("-p", "--port", help="Port of this server.")
@click.option("-d", "--delete", is_flag=True, help="Delete this server.")
@click.argument("bus", nargs=1)
@click.argument("name", nargs=-1)
@click.pass_obj
async def server_(obj, bus, name, host, port, delete):
    """
    Configure a server for a bus.
    """
    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(obj.cfg.knx.prefix, bus, min_depth=1, max_depth=1):
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
        res = await obj.client.delete_tree(obj.cfg.knx.prefix | name, nchain=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        return
    else:
        value = None
    await _attr(obj, (), value, (bus, name), False)


@cli.command()
@click.option("-l", "--local-ip", help="Force this local IP address.")
@click.option("-i", "--initial", is_flag=True, help="Push existing outgoing states.")
@click.argument("bus", nargs=1)
@click.argument("server", nargs=-1)
@click.pass_obj
async def monitor(obj, bus, server, local_ip, initial):
    """Stand-alone task to talk to a single server."""
    from distkv_ext.knx.task import task
    from distkv_ext.knx.model import KNXroot

    knx = await KNXroot.as_handler(obj.client)
    await knx.wait_loaded()

    if not server and " " in bus:
        bus, server = bus.split(" ")
    elif len(server) != 1:
        raise click.UsageError("Use a single server name")
    else:
        server = server[0]

    async with as_service(obj) as srv:
        await task(
            obj.client, obj.cfg.knx, knx[bus][server], srv, local_ip=local_ip, initial=initial
        )
