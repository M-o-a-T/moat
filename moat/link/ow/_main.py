"""
Command-line interface for moat.link.ow.

The configuration is keyed by device (see `moat.link.ow.model`), so that
devices can move between buses. Devices are addressed as
``FAMILY.CODE`` with two and twelve hex digits.
"""

from __future__ import annotations

import logging
import sys

import asyncclick as click

from moat.util import NotGiven, yprint
from moat.lib.path import P, Path
from moat.lib.run import AliasedGroup, attr_args, process_args
from moat.link._data import data_get, node_attr
from moat.link.client import Link

from .model import SERVER, fmt_code, fmt_device, fmt_family, parse_at

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


@click.group(cls=AliasedGroup, name="ow", short_help="Manage 1-Wire (OWFS) devices.")
@click.pass_context
async def cli(ctx) -> None:
    """
    Manager for 1-Wire (OWFS) servers and devices.

    \b
    … server -                    list servers
    … server NAME [add|set|delete]
    … at -                        list device families
    … at FAMILY                   list devices; get/set common settings
    … at FAMILY.CODE              get/set device settings, list mappings
    … at FAMILY.CODE.ATTR         get/add/set/delete an attribute mapping
    … monitor [NAME…]             run the connector

    FAMILY and CODE are hex numbers (2 and 12 digits).
    """
    obj = ctx.obj
    obj.conn = await ctx.with_async_resource(Link(obj.cfg["link"]))
    obj.ow_prefix = obj.cfg.link.ow.prefix


def _hex_keys(p: Path, depth: int = 0) -> Path:
    "Show the family and device elements of a path (that starts at @depth) in hex."
    res = []
    for i, k in enumerate(p, start=depth):
        if i == 0 and isinstance(k, int):
            k = fmt_family(k)  # noqa:PLW2901
        elif i == 1 and isinstance(k, int):
            k = fmt_code(k)  # noqa:PLW2901
        res.append(k)
    return Path.build(res)


async def _list(obj, path: Path, fmt) -> int:
    "List the integer children of @path, formatted by @fmt."
    cnt = 0
    keys = [k async for k in obj.conn.d_list(path)]
    for k in sorted(k for k in keys if isinstance(k, int)):
        cnt += 1
        print(fmt(k), file=obj.stdout)
    if not cnt and obj.debug:
        print("no entries", file=sys.stderr)
    return cnt


# Servers


@cli.group(
    "server",
    cls=AliasedGroup,
    invoke_without_command=True,
    short_help="Manage owservers.",
)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def server_(ctx, name: str) -> None:
    """
    Manage an owserver.

    Use '-' to list all servers. Without a subcommand, show a server's
    settings.
    """
    obj = ctx.obj
    obj.ow_server = obj.ow_prefix / SERVER / name
    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.UsageError("The name '-' lists servers and precludes subcommands.")
        cnt = 0
        async for k in obj.conn.d_list(obj.ow_prefix / SERVER):
            cnt += 1
            print(k, file=obj.stdout)
        if not cnt and obj.debug:
            print("no entries", file=sys.stderr)
        return
    if ctx.invoked_subcommand is None:
        try:
            data = await obj.conn.d_get(obj.ow_server)
        except KeyError:
            raise click.UsageError(f"Server {name!r} does not exist.") from None
        yprint(data, stream=obj.stdout)


def _server_options(proc):
    """Decorate ``add``/``set`` with the server-config options."""
    proc = click.option("-p", "--port", type=int, help="Port of the owserver (default 4304).")(
        proc
    )
    proc = click.option("-h", "--host", type=str, help="Host name or IP of the owserver.")(proc)
    return proc


@server_.command("add", short_help="Add an owserver")
@_server_options
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing server.")
@click.pass_obj
async def server_add(obj, host, port, force) -> None:
    """Add an owserver."""
    if host is None:
        raise click.UsageError("You need to set the host ('-h').")
    if not force:
        try:
            await obj.conn.d_get(obj.ow_server)
        except KeyError:
            pass
        else:
            raise click.UsageError(
                f"Server {obj.ow_server[-1]!r} already exists. Use --force or 'set'."
            )
    srv: dict[str, Any] = {"host": host}
    if port is not None:
        srv["port"] = port
    await obj.conn.d_set(obj.ow_server, {SERVER: srv})


@server_.command("set", short_help="Modify an owserver")
@_server_options
@click.pass_obj
async def server_set(obj, host, port) -> None:
    """Modify an owserver."""
    try:
        data = await obj.conn.d_get(obj.ow_server)
    except KeyError:
        raise click.UsageError(f"Server {obj.ow_server[-1]!r} does not exist.") from None
    data = dict(data) if isinstance(data, dict) else {}
    srv = data.get(SERVER)
    srv = dict(srv) if isinstance(srv, dict) else {}
    if host is not None:
        srv["host"] = host
    if port is not None:
        srv["port"] = port
    data[SERVER] = srv
    await obj.conn.d_set(obj.ow_server, data)


@server_.command("delete", short_help="Delete an owserver")
@click.pass_obj
async def server_delete(obj) -> None:
    """Delete an owserver."""
    try:
        await obj.conn.d_get(obj.ow_server)
    except KeyError:
        raise click.UsageError(f"Server {obj.ow_server[-1]!r} does not exist.") from None
    await obj.conn.d_set(obj.ow_server, NotGiven)


@server_.command("monitor")
@click.option("-f", "--force", is_flag=True, help="Take over if announced elsewhere.")
@click.pass_obj
async def server_monitor(obj, force: bool) -> None:
    """
    Run the 1-Wire connector for this owserver only.

    Connection problems are reported and retried. Other errors end the
    connector (unlike 'moat link ow monitor', which logs and retries
    them), so that e.g. systemd can restart it.
    """
    from moat.util.systemd import as_service  # noqa: PLC0415

    from .task import task  # noqa: PLC0415

    name = obj.ow_server[-1]
    try:
        await obj.conn.d_get(obj.ow_server)
    except KeyError:
        raise click.UsageError(f"Server {name!r} does not exist.") from None
    async with as_service(obj) as srv:
        await task(obj.conn, obj.cfg, (name,), force=force, crash=True, task_status=srv)


# Families, devices, attributes


@cli.group(
    "at",
    cls=AliasedGroup,
    invoke_without_command=True,
    short_help="Manage device settings and attribute mappings.",
)
@click.argument("spec", type=str, nargs=1)
@click.pass_context
async def at_(ctx, spec: str) -> None:
    """
    Manage a device family, a device, or an attribute mapping.

    \b
    SPEC is
    -                   list the device families
    FAMILY              list the family's devices
    FAMILY.CODE         list the device's attribute mappings
    FAMILY.CODE.ATTR    show an attribute mapping

    Use 'get' and 'set' for the settings at that level. A family's and a
    device's settings are inherited by the attribute mappings below them.
    """
    obj = ctx.obj
    if spec == "-":
        if ctx.invoked_subcommand is not None:
            raise click.UsageError("'-' lists families and precludes subcommands.")
        await _list(obj, obj.ow_prefix, fmt_family)
        return
    try:
        fam, code, attr = parse_at(spec)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None

    obj.ow_family = fam
    obj.ow_code = code
    obj.ow_attr = attr
    obj.ow_path = obj.ow_prefix / fam
    if code is not None:
        obj.ow_path = obj.ow_path / code + attr

    if ctx.invoked_subcommand is not None:
        return
    if code is None:
        await _list(obj, obj.ow_path, lambda c: fmt_device(fam, c))
    elif not len(attr):
        cnt = 0
        async with obj.conn.d_walk(obj.ow_path, min_depth=1) as mon:
            async for p, _d in mon:
                cnt += 1
                print(f"{fmt_device(fam, code)}.{p}", file=obj.stdout)
        if not cnt and obj.debug:
            print("no entries", file=sys.stderr)
    else:
        await _get(obj, ())


async def _get(obj, attrs) -> None:
    try:
        data = await obj.conn.d_get(obj.ow_path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    if not attrs:
        yprint(data, stream=obj.stdout)
        return

    def _lookup(a: Path) -> Any:
        v = data
        for k in a:
            try:
                v = v[k]
            except (KeyError, IndexError, TypeError):
                raise click.UsageError(f"Not found: {a}") from None
        return v

    if len(attrs) == 1:
        yprint(_lookup(attrs[0]), stream=obj.stdout)
    else:
        yprint({str(a): _lookup(a) for a in attrs}, stream=obj.stdout)


@at_.command("get")
@click.argument("attrs", type=P, nargs=-1)
@click.pass_obj
async def at_get(obj, attrs: tuple[Path, ...]) -> None:
    """
    Show the settings at this level.

    ATTRS are lookup paths into the settings; without them, show all.
    """
    await _get(obj, attrs)


@at_.command("set")
@attr_args
@click.pass_obj
async def at_set(obj, **kw) -> None:
    """
    Modify the settings at this level.

    Family and device settings are defaults for the mappings below them,
    e.g. '-s interval =30'.
    """
    try:
        val = await obj.conn.d_get(obj.ow_path)
    except KeyError:
        val = {}
    res, _meta = await node_attr(obj, obj.ow_path, val=val, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_.command("add", short_help="Add an attribute mapping")
@attr_args
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry.")
@click.option(
    "-w",
    "--write",
    is_flag=True,
    help="Write direction (Link→device); needs 'src'. Default: read (device→Link).",
)
@click.option("-i", "--interval", type=float, help="Polling interval in seconds (read).")
@click.option(
    "-a",
    "--attr",
    "attr_",
    help="Sub-attribute path: 'src_attr' for write, 'dest_attr' for read.",
)
@click.pass_obj
async def at_add(obj, write, interval, attr_, force, **kw) -> None:
    """
    Add an attribute mapping (FAMILY.CODE.ATTR).

    For the read direction (default) set ``dest`` to the MoaT-Link path
    that receives the polled value; for the write direction ('-w') set
    ``src`` to the path whose changes are written to the device, e.g.
    '-s dest .my.path'. The interval may also be inherited from the
    device or family.
    """
    if not len(obj.ow_attr):
        raise click.UsageError("Use FAMILY.CODE.ATTR to add an attribute mapping.")
    path = obj.ow_path
    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError("This entry already exists. Use '--force' or 'set'.")

    val: dict[str | None, Any] = {}
    if attr_ is not None:
        val["src_attr" if write else "dest_attr"] = P(attr_)
    if not write and interval is not None:
        val["interval"] = interval

    res = process_args(val, **kw)
    required = "src" if write else "dest"
    if not isinstance(res, dict) or res.get(required) is None:
        raise click.UsageError(
            f"For the {'write' if write else 'read'} direction you must set the "
            f"{required!r} attribute, e.g. `-s {required} .some.path`."
        )
    await obj.conn.d_set(path, res)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_.command("delete")
@click.option("-r", "--recursive", is_flag=True, help="Also delete everything below.")
@click.pass_obj
async def at_delete(obj, recursive: bool) -> None:
    """Delete the settings at this level."""
    if recursive:
        await obj.conn.d.delete(obj.ow_path, rec=True)
        return
    try:
        await obj.conn.d_get(obj.ow_path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    await obj.conn.d_set(obj.ow_path, NotGiven)


@at_.command("dump")
@click.pass_obj
async def at_dump(obj) -> None:
    """Show the subtree as YAML (family and device codes in hex)."""
    depth = 1 if obj.ow_code is None else 2 + len(obj.ow_attr)
    await data_get(
        obj.conn,
        obj.ow_path,
        recursive=True,
        path_mangle=lambda p: _hex_keys(p, depth),
        out=obj.stdout,
    )


@cli.command("dump")
@click.pass_obj
async def dump_(obj) -> None:
    """Show the whole configuration as YAML (family and device codes in hex)."""
    await data_get(obj.conn, obj.ow_prefix, recursive=True, path_mangle=_hex_keys, out=obj.stdout)


@cli.command()
@click.option("-f", "--force", is_flag=True, help="Take over servers announced elsewhere.")
@click.argument("servers", type=str, nargs=-1)
@click.pass_obj
async def monitor(obj, servers: tuple[str, ...], force: bool) -> None:
    """
    Run the 1-Wire connector.

    Talks to all owservers (or the SERVERS given). Each server is
    announced, so that several connectors can share the work; a server
    that another live connector has announced is skipped until that
    one goes away, unless '--force' is used.

    Errors are reported to the error subsystem and retried. Use
    'moat link ow server NAME monitor' to run a single server.
    """
    from moat.util.systemd import as_service  # noqa: PLC0415

    from .task import task  # noqa: PLC0415

    async with as_service(obj) as srv:
        await task(obj.conn, obj.cfg, servers, force=force, task_status=srv)
