"""
Command-line interface for moat.link.ow.

Manages 1-Wire (OWFS) servers and their per-attribute mirror entries.
The ``at`` sub-group targets a single device attribute identified by a
1-Wire device id (``FF.CODE.CHK``) and an attribute path.
"""

from __future__ import annotations

import logging
import sys

import asyncclick as click

from moat.util import NotGiven, yprint
from moat.lib.path import P, Path
from moat.lib.run import AliasedGroup, attr_args
from moat.link._data import data_get, node_attr
from moat.link.announce import as_service
from moat.link.client import Link

from .model import device_subpath

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def _server_path(obj) -> Path:
    """Return the link path of the currently-selected OWFS server."""
    return obj.ow_prefix + Path.build((obj.ow_name,))


async def _require_server(obj) -> dict[str, Any]:
    """Fetch the data stored at the server entry, or raise.

    Raises:
        click.UsageError: if the entry is missing or not a mapping.
    """
    try:
        data = await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(f"Server {obj.ow_name!r} does not exist.") from None
    if not isinstance(data, dict):
        raise click.UsageError(f"Server {obj.ow_name!r} has no configuration.")
    return data


@click.group(
    cls=AliasedGroup,
    name="ow",
    short_help="Manage 1-Wire (OWFS) servers.",
    invoke_without_command=True,
    help="""\
        Manager for 1-Wire (OWFS) bus servers.

        \b
        Use '… ow -' to list all servers.
        Use '… ow NAME' to show details of a single server.
        """,
)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def cli(ctx, name: str) -> None:
    """Dispatch to a server- or attribute-specific subcommand."""
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    obj.ow_cfg = obj.cfg.link.ow
    obj.ow_prefix = obj.ow_cfg.prefix
    obj.ow_name = name

    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The name '-' triggers a list and precludes subcommands.",
            )
        cnt = 0
        async with obj.conn.d_walk(obj.ow_prefix, min_depth=1, max_depth=1) as mon:
            async for p, _d in mon:
                cnt += 1
                print(p[-1], file=obj.stdout)
        if not cnt and obj.debug:
            print("no entries", file=sys.stderr)
        return

    if ctx.invoked_subcommand is None:
        try:
            data = await obj.conn.d_get(_server_path(obj))
        except KeyError:
            raise click.UsageError(
                f"Server {obj.ow_name!r} does not exist.",
            ) from None
        srv = data.get("server", {}) if isinstance(data, dict) else {}
        cnt = 0
        if isinstance(srv, dict):
            for k in ("host", "port"):
                v = srv.get(k)
                if v is not None:
                    cnt += 1
                    print(f"server {k} {v}", file=obj.stdout)
        if not cnt and obj.debug:
            print("exists, no data", file=sys.stderr)


def _server_options(proc):
    """Decorate ``add``/``set`` with the server-config options."""
    proc = click.option(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Port of the owserver (default 4304).",
    )(proc)
    proc = click.option(
        "-h",
        "--host",
        type=str,
        default=None,
        help="Host name or IP of the owserver.",
    )(proc)
    return proc


@cli.command(short_help="Add an OWFS server")
@_server_options
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing server.")
@click.pass_obj
async def add(obj, host, port, force) -> None:
    """Add an OWFS server (owserver)."""
    path = _server_path(obj)
    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError(
                f"Server {obj.ow_name!r} already exists. Use --force or 'set'.",
            )

    srv: dict[str, Any] = {}
    if host is not None:
        srv["host"] = host
    if port is not None:
        srv["port"] = port
    await obj.conn.d_set(path, {"server": srv})


@cli.command("set", short_help="Modify an OWFS server")
@_server_options
@click.pass_obj
async def set_(obj, host, port) -> None:
    """Modify an OWFS server.

    Pass ``-`` as a value (where applicable) to clear an existing setting.
    """
    data = await _require_server(obj)
    srv = data.get("server", {})
    if not isinstance(srv, dict):
        srv = {}

    if host is not None:
        if host == "-":
            srv.pop("host", None)
        else:
            srv["host"] = host
    if port is not None:
        srv["port"] = port
    data["server"] = srv

    await obj.conn.d_set(_server_path(obj), data)


@cli.command("delete", short_help="Delete an OWFS server")
@click.option("-r", "--recursive", is_flag=True, help="Also remove all entries below.")
@click.pass_obj
async def delete_(obj, recursive: bool) -> None:
    """Delete an OWFS server.

    Without ``--recursive`` the server entry itself is removed but its
    child attribute entries are kept (they become orphans).
    """
    path = _server_path(obj)
    args: dict[str, Any] = {}
    if recursive:
        args["rec"] = True
    res = await obj.conn.d.delete(path, **args)
    if getattr(obj, "meta", False):
        yprint(res[0], stream=obj.stdout)


@cli.command("dump")
@click.option("-l", "--one-line", is_flag=True, help="Single line per entry")
@click.pass_obj
async def dump_(obj, one_line: bool) -> None:
    """Emit a server's (sub)state as a list / YAML file."""
    path = _server_path(obj)
    if not one_line:
        await data_get(obj.conn, path, recursive=True, out=obj.stdout)
        return
    async with obj.conn.d_walk(path) as mon:
        async for p, d in mon:
            print(f"{path + p} {d}", file=obj.stdout)


@cli.group(
    "at",
    invoke_without_command=True,
    short_help="create/show/delete an attribute mapping",
)
@click.argument("device", type=str, nargs=1)
@click.argument("attr", type=str, nargs=1)
@click.pass_context
async def at_cli(ctx, device: str, attr: str) -> None:
    """Manage a single 1-Wire attribute mapping under a server.

    DEVICE is a 1-Wire device id in ``FF.CODE.CHK`` form (the checksum is
    ignored); ATTR is the device attribute path, e.g. ``temperature`` or
    ``foo.bar``.
    """
    obj = ctx.obj
    try:
        dev_sub = device_subpath(device)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    try:
        sub = dev_sub + P(attr)
    except Exception as exc:
        raise click.UsageError(f"Bad attribute {attr!r}: {exc}") from None
    try:
        await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(
            "Create the server before mapping attributes to it!",
        ) from None
    obj.ow_subpath = sub
    if ctx.invoked_subcommand is None:
        await data_get(
            obj.conn,
            _server_path(obj) + sub,
            recursive=False,
            out=obj.stdout,
        )


@at_cli.command("dump")
@click.option("-l", "--one-line", is_flag=True, help="Single line per entry")
@click.pass_obj
async def dump_at(obj, one_line: bool) -> None:
    """Emit a subtree as a list / YAML file."""
    path = _server_path(obj) + obj.ow_subpath
    if not one_line:
        await data_get(obj.conn, path, recursive=True, out=obj.stdout)
        return
    async with obj.conn.d_walk(path) as mon:
        async for p, d in mon:
            print(f"{path + p} {d}", file=obj.stdout)


@at_cli.command("add", short_help="Add an attribute mapping")
@attr_args
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry.")
@click.option(
    "-w",
    "--write",
    is_flag=True,
    help="Write direction (Link→device); needs 'src'. Default: read (device→Link).",
)
@click.option(
    "-i",
    "--interval",
    type=float,
    default=None,
    help="Polling interval in seconds (read direction).",
)
@click.option(
    "-a",
    "--attr",
    "attr_",
    default=None,
    help="Sub-attribute path: 'src_attr' for write, 'dest_attr' for read.",
)
@click.pass_obj
async def add_at(obj, write, interval, attr_, force, **kw) -> None:
    """Add a 1-Wire attribute mapping.

    \b
    DEVICE ATTR: identify the device attribute. Required.

    For read direction (default) set ``dest`` to the MoaT-Link path that
    receives the polled value; for write direction (``-w``) set ``src``
    to the MoaT-Link path whose changes are forwarded to the device.

    Use the ``-s`` option to set attributes, e.g. ``-s dest .my.path``
    or ``-s src .my.path``.
    """
    sub: Path = obj.ow_subpath
    path = _server_path(obj) + sub

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

    res, _meta = await node_attr(obj, path, val=val, **kw)

    required = "src" if write else "dest"
    if not isinstance(res, dict) or res.get(required) is None:
        raise click.UsageError(
            f"For {'write' if write else 'read'} direction you must set the "
            f"{required!r} attribute, e.g. `-s {required} .some.path`.",
        )

    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def set_at(obj, **kw) -> None:
    """Modify a 1-Wire attribute mapping."""
    path = _server_path(obj) + obj.ow_subpath
    res, _meta = await node_attr(obj, path, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_cli.command("delete")
@click.pass_obj
async def delete_at(obj) -> None:
    """Remove an attribute mapping from the server."""
    path = _server_path(obj) + obj.ow_subpath
    try:
        await obj.conn.d_get(path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    await obj.conn.d_set(path, NotGiven)


@cli.command()
@click.pass_obj
async def monitor(obj) -> None:
    """Stand-alone task to talk to a single OWFS server."""
    from .task import task  # noqa: PLC0415

    async with as_service(obj, host=False) as srv:
        await task(
            obj.conn,
            obj.ow_cfg,
            obj.ow_name,
            task_status=srv,
        )
