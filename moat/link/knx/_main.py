"""
Command-line interface for moat.link.knx.

Mirrors :mod:`moat.link.metrics` but with KNX-specific argument
parsing: the ``at`` sub-group takes a KNX ``a/b/c`` group address that
is decoded to a 3-element integer subpath.
"""

from __future__ import annotations

import logging
import sys

import asyncclick as click

from moat.util import NotGiven, yprint
from moat.lib.path import Path
from moat.lib.run import AliasedGroup, attr_args
from moat.link._data import data_get, node_attr
from moat.link.announce import as_service
from moat.link.client import Link

from .model import group_subpath

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def _server_path(obj) -> Path:
    """Return the link path of the currently-selected KNX server."""
    return obj.knx_prefix + Path.build((obj.knx_name,))


async def _require_server(obj) -> dict[str, Any]:
    """Fetch the data stored at the server entry, or raise.

    Raises:
        click.UsageError: if the entry is missing or not a mapping.
    """
    try:
        data = await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(f"Server {obj.knx_name!r} does not exist.") from None
    if not isinstance(data, dict):
        raise click.UsageError(f"Server {obj.knx_name!r} has no configuration.")
    return data


@click.group(
    cls=AliasedGroup,
    name="knx",
    short_help="Manage KNX gateways.",
    invoke_without_command=True,
    help="""\
        Manager for KNX bus gateways.

        \b
        Use '… knx -' to list all entries.
        Use '… knx NAME' to show details of a single entry.
        """,
)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def cli(ctx, name: str) -> None:
    """Dispatch to a server- or address-specific subcommand."""
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    obj.knx_cfg = obj.cfg.link.knx
    obj.knx_prefix = obj.knx_cfg.prefix
    obj.knx_name = name

    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The name '-' triggers a list and precludes subcommands.",
            )
        cnt = 0
        async with obj.conn.d_walk(obj.knx_prefix, min_depth=1, max_depth=1) as mon:
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
                f"Server {obj.knx_name!r} does not exist.",
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
        help="Port of the KNX/IP gateway (default 3671).",
    )(proc)
    proc = click.option(
        "-h",
        "--host",
        type=str,
        default=None,
        help="Host name or IP of the KNX/IP gateway.",
    )(proc)
    return proc


@cli.command(short_help="Add a KNX gateway")
@_server_options
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing gateway.")
@click.pass_obj
async def add(obj, host, port, force) -> None:
    """Add a KNX gateway."""
    path = _server_path(obj)
    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError(
                f"Gateway {obj.knx_name!r} already exists. Use --force or 'set'.",
            )

    srv: dict[str, Any] = {}
    if host is not None:
        srv["host"] = host
    if port is not None:
        srv["port"] = port
    await obj.conn.d_set(path, {"server": srv})


@cli.command("set", short_help="Modify a KNX gateway")
@_server_options
@click.pass_obj
async def set_(obj, host, port) -> None:
    """Modify a KNX gateway.

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


@cli.command("delete", short_help="Delete a KNX gateway")
@click.option("-r", "--recursive", is_flag=True, help="Also remove all entries below.")
@click.pass_obj
async def delete_(obj, recursive: bool) -> None:
    """Delete a KNX gateway.

    Without ``--recursive`` the gateway entry itself is removed but its
    child group-address entries are kept (they become orphans).
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
    """Emit a gateway's (sub)state as a list / YAML file."""
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
    short_help="create/show/delete an entry",
    cls=AliasedGroup,
)
@click.argument("group", type=str, nargs=1)
@click.pass_context
async def at_cli(ctx, group: str) -> None:
    """Manage a single KNX group-address entry under a gateway.

    GROUP is a KNX group address in ``a/b/c`` form.  It is translated to
    the integer subpath ``a:b:c`` below the gateway.
    """
    obj = ctx.obj
    try:
        sub = group_subpath(group)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    try:
        await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(
            "Create the gateway before assigning group addresses to it!",
        ) from None
    obj.knx_subpath = sub
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
    path = _server_path(obj) + obj.knx_subpath
    if not one_line:
        await data_get(obj.conn, path, recursive=True, out=obj.stdout)
        return
    async with obj.conn.d_walk(path) as mon:
        async for p, d in mon:
            print(f"{path + p} {d}", file=obj.stdout)


@at_cli.command("add", short_help="Add an entry")
@attr_args
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry.")
@click.option(
    "-t",
    "--type",
    "typ",
    type=click.Choice(["in", "out"]),
    required=True,
    help="Direction: 'in' (KNX→Link) or 'out' (Link→KNX).",
)
@click.option(
    "-m",
    "--mode",
    required=True,
    help="XKNX data-point type, e.g. 'binary' or 'Bool'.",
)
@click.pass_obj
async def add_at(obj, typ, mode, force, **kw) -> None:
    """Add a group-address mapping.

    \b
    GROUP: a KNX ``a/b/c`` group address. Required.

    For ``type=in`` the ``dest`` attribute must specify the
    destination MoaT-Link path; for ``type=out`` the ``src``
    attribute must specify the source path.  Use the ``-s``
    option to set them, e.g. ``-s dest .my.path``.

    For ``type=out`` you may additionally set ``state`` to a
    MoaT-Link path that tracks the last observed bus state.
    Commands whose timestamp is older than the recorded state
    are then suppressed (useful on startup).
    """
    sub: Path = obj.knx_subpath
    path = _server_path(obj) + sub

    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError("This entry already exists. Use '--force' or 'set'.")

    val: dict[str | None, Any] = {"type": typ, "mode": mode}
    res, _meta = await node_attr(obj, path, val=val, **kw)

    required = "dest" if typ == "in" else "src"
    if not isinstance(res, dict) or res.get(required) is None:
        raise click.UsageError(
            f"For type={typ!r} you must set the {required!r} attribute, "
            f"e.g. `-s {required} .some.path`.",
        )

    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_cli.command("delete")
@click.pass_obj
async def delete_at(obj) -> None:
    """Remove a group-address mapping from the gateway."""
    path = _server_path(obj) + obj.knx_subpath
    try:
        await obj.conn.d_get(path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    await obj.conn.d_set(path, NotGiven)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def set_at(obj, **kw) -> None:
    """Modify a group-address mapping."""
    path = _server_path(obj) + obj.knx_subpath
    res, _meta = await node_attr(obj, path, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@cli.command()
@click.option("-l", "--local-ip", default=None, help="Force this local IP address.")
@click.option("-i", "--initial", is_flag=True, help="Push existing outgoing states.")
@click.pass_obj
async def monitor(obj, local_ip, initial) -> None:
    """Stand-alone task to talk to a single KNX gateway."""
    from .task import task  # noqa: PLC0415

    async with as_service(obj, host=False) as srv:
        await task(
            obj.conn,
            obj.knx_cfg,
            obj.knx_name,
            local_ip=local_ip,
            initial=initial,
            task_status=srv,
        )
