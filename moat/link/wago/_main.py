"""
Command-line interface for moat.link.wago.
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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def _server_path(obj) -> Path:
    """Return the link path of the currently-selected Wago server."""
    return obj.wago_prefix + Path.build((obj.wago_name,))


async def _require_server(obj) -> dict[str, Any]:
    """Fetch the data stored at the server entry, or raise.

    Raises:
        click.UsageError: if the entry is missing or not a mapping.
    """
    try:
        data = await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(f"Server {obj.wago_name!r} does not exist.") from None
    if not isinstance(data, dict):
        raise click.UsageError(f"Server {obj.wago_name!r} has no configuration.")
    return data


@click.group(
    cls=AliasedGroup,
    name="wago",
    short_help="Manage Wago controllers.",
    invoke_without_command=True,
    help="""\
        Manager for Wago bus controllers.

        \b
        Use '… wago -' to list all entries.
        Use '… wago NAME' to show details of a single entry.
        """,
)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def cli(ctx, name: str) -> None:
    """Dispatch to a server- or port-specific subcommand."""
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    obj.wago_cfg = obj.cfg.link.wago
    obj.wago_prefix = obj.wago_cfg.prefix
    obj.wago_name = name

    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The name '-' triggers a list and precludes subcommands.",
            )
        cnt = 0
        async with obj.conn.d_walk(obj.wago_prefix, min_depth=1, max_depth=1) as mon:
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
                f"Server {obj.wago_name!r} does not exist.",
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
        help="Port of the Wago controller (default 29995).",
    )(proc)
    proc = click.option(
        "-h",
        "--host",
        type=str,
        default=None,
        help="Host name or IP of the Wago controller.",
    )(proc)
    return proc


@cli.command(short_help="Add a Wago controller")
@_server_options
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing controller.")
@click.pass_obj
async def add(obj, host, port, force) -> None:
    """Add a Wago controller."""
    path = _server_path(obj)
    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError(
                f"Controller {obj.wago_name!r} already exists. Use --force or 'set'.",
            )

    srv: dict[str, Any] = {}
    if host is not None:
        srv["host"] = host
    if port is not None:
        srv["port"] = port
    await obj.conn.d_set(path, {"server": srv})


@cli.command("set", short_help="Modify a Wago controller")
@_server_options
@click.pass_obj
async def set_(obj, host, port) -> None:
    """Modify a Wago controller.

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


@cli.command("delete", short_help="Delete a Wago controller")
@click.option("-r", "--recursive", is_flag=True, help="Also remove all entries below.")
@click.pass_obj
async def delete_(obj, recursive: bool) -> None:
    """Delete a Wago controller.

    Without ``--recursive`` the controller entry itself is removed but its
    child port entries are kept (they become orphans).
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
    """Emit a controller's (sub)state as a list / YAML file."""
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
    short_help="Create/show/delete a port entry.",
)
@click.argument("type_", type=str, nargs=1)
@click.argument("card", type=int, nargs=1)
@click.argument("port", type=int, nargs=1)
@click.pass_context
async def at_cli(ctx, type_: str, card: int, port: int) -> None:
    """Manage a single port entry under a controller.

    TYPE is ``input`` or ``output``.  CARD and PORT are integers.
    """
    obj = ctx.obj
    if type_ not in ("input", "output"):
        raise click.UsageError("TYPE must be 'input' or 'output'.")
    try:
        await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(
            "Create the controller before assigning ports to it!",
        ) from None
    obj.wago_subpath = Path.build((type_, card, port))
    if ctx.invoked_subcommand is None:
        await data_get(
            obj.conn,
            _server_path(obj) + obj.wago_subpath,
            recursive=False,
            out=obj.stdout,
        )


@at_cli.command("dump")
@click.option("-l", "--one-line", is_flag=True, help="Single line per entry")
@click.pass_obj
async def dump_at(obj, one_line: bool) -> None:
    """Emit a subtree as a list / YAML file."""
    path = _server_path(obj) + obj.wago_subpath
    if not one_line:
        await data_get(obj.conn, path, recursive=True, out=obj.stdout)
        return
    async with obj.conn.d_walk(path) as mon:
        async for p, d in mon:
            print(f"{path + p} {d}", file=obj.stdout)


@at_cli.command("add", short_help="Add a port entry")
@attr_args
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry.")
@click.option(
    "-m",
    "--mode",
    required=True,
    help='Port mode: "read", "count", "write", "oneshot", or "pulse".',
)
@click.pass_obj
async def add_at(obj, mode, force, **kw) -> None:
    """Add a port mapping.

    \b
    TYPE CARD PORT: identify the physical port. Required.

    Use the ``-s`` option to set attributes like ``dest`` or ``src``,
    e.g. ``-s dest .my.path``.
    """
    sub: Path = obj.wago_subpath
    path = _server_path(obj) + sub

    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError("This entry already exists. Use '--force' or 'set'.")

    val: dict[str | None, Any] = {"mode": mode}
    res, _meta = await node_attr(obj, path, val=val, **kw)

    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@at_cli.command("delete")
@click.pass_obj
async def delete_at(obj) -> None:
    """Remove a port mapping from the controller."""
    path = _server_path(obj) + obj.wago_subpath
    try:
        await obj.conn.d_get(path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    await obj.conn.d_set(path, NotGiven)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def set_at(obj, **kw) -> None:
    """Modify a port entry."""
    path = _server_path(obj) + obj.wago_subpath
    res, _meta = await node_attr(obj, path, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
async def monitor(obj) -> None:
    """Stand-alone task to talk to a single Wago controller."""
    from .task import task  # noqa: PLC0415

    async with as_service(obj, host=False) as srv:
        await task(
            obj.conn,
            obj.wago_cfg,
            obj.wago_name,
            task_status=srv,
        )
