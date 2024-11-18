# command line interface

import asyncclick as click
from collections.abc import Mapping

from moat.kv.data import res_get, res_update, node_attr
from moat.util import yprint, attrdict, NotGiven, as_service, P, Path, path_eval, attr_args

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
    cfg = obj.cfg.kv.knx
    res = {}
    path = P(path)
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        cfg.prefix + path, nchain=obj.meta, max_depth=4 - len(path)
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
    cfg = obj.cfg.kv.knx
    path = P(path)
    if len(path) > 4:
        raise click.UsageError("Only up to four path elements allowed")

    async for r in obj.client.get_tree(
        cfg.prefix + path, nchain=obj.meta, min_depth=1, max_depth=1, empty=True
    ):
        if len(path) and not isinstance(r.path[-1], int):
            continue
        print(r.path[-1], file=obj.stdout)


@cli.command("attr")
@attr_args
@click.argument("bus", nargs=1)
@click.argument("group", nargs=1)
@click.pass_obj
async def attr_(obj, bus, group, vars_, eval_, path_):
    """Set/get/delete an attribute on a given KNX element.

    `--eval` without a value deletes the attribute.
    """
    cfg = obj.cfg.kv.knx
    group = (int(x) for x in group.split("/")) if group else ()
    path = Path(bus, *group)
    if len(path) != 4:
        raise click.UsageError("Group address must be 3 /-separated elements.")
 
    res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 1)

    if vars_ or eval_ or path_:
        res = await node_attr(obj, cfg.prefix + path, vars_,eval_,path_, res=res)
        if obj.meta:
            yprint(res, stream=obj.stdout)
    else:
        if not obj.meta:
            res = res.value
        yprint(res, stream=obj.stdout)

def map_keys():
    try:
        return RemoteValueSensor.DPTMAP.keys()
    except AttributeError:
        from xknx.dpt import DPTBase
        return (cls.__name__[3:] for cls in DPTBase.__recursive_subclasses__())

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

Known modes: {" ".join(map_keys())}
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
    cfg = obj.cfg.kv.knx
    group = (int(x) for x in group.split("/"))
    path = Path(bus, *group)
    if len(path) != 4:
        raise click.UsageError("Group address must be 3 /-separated elements.")
    res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 1)
    val = res.get("value", attrdict())

    if typ == "-":
        res = await obj.client.delete(cfg.prefix + path, nchain=obj.meta)
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
    cfg = obj.cfg.kv.knx
    if res is None:
        res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 1)
    try:
        val = res.value
    except AttributeError:
        res.chain = None
    if eval_:
        if value is None:
            pass ## value = res_delete(res, attr)
        else:
            value = path_eval(value)
            if isinstance(value, Mapping):
                # replace
                pass ## value = res_delete(res, attr)
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
        cfg.prefix + path, value=value, nchain=obj.meta, chain=res.chain
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
    cfg = obj.cfg.kv.knx
    if not name:
        if host or port or delete:
            raise click.UsageError("Use a server name to set parameters")
        async for r in obj.client.get_tree(cfg.prefix / bus, min_depth=1, max_depth=1):
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
        res = await obj.client.delete_tree(cfg.prefix | name, nchain=obj.meta)
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
    from .task import task
    from .model import KNXroot
    cfg = obj.cfg.kv.knx

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
            obj.client, cfg, knx[bus][server], srv, local_ip=local_ip, initial=initial
        )
