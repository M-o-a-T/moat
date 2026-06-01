"""
Command-line interface for moat.link.metrics.

The structure mirrors the legacy ``./mt kv akumuli`` command. A metrics
*server* entry is created or modified at the top level, and individual
series mappings live below it, accessed through the ``at`` sub-group.

The only conceptual addition over the legacy command is the
``--backend`` option on the server, which selects the metrics back-end
driver. ``add --help`` / ``set --help`` show the list of available
back-ends.
"""

from __future__ import annotations

import logging
import pkgutil
import sys

import asyncclick as click

import moat.link.metrics.backend as _backend_pkg
from moat.util import NotGiven, attrdict, yprint
from moat.lib.path import P, Path
from moat.lib.run import AliasedGroup, attr_args
from moat.link._data import data_get, node_attr
from moat.link.announce import as_service
from moat.link.client import Link

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

_backends: list[str] = sorted(
    m.name for m in pkgutil.iter_modules(_backend_pkg.__path__) if not m.name.startswith("_")
)
_backends_epilog: str = "Available back-ends: " + (", ".join(_backends) or "(none)") + "."


def _server_path(obj) -> Path:
    """Return the link path of the currently-selected metrics server."""
    return obj.metrics_prefix + Path.build((obj.metrics_name,))


@click.group(
    cls=AliasedGroup,
    name="metrics",
    short_help="Manage metrics time-series servers.",
    invoke_without_command=True,
    help="""\
        Manager for metrics time-series logging.

        \b
        Use '… metrics -' to list all entries.
        Use '… metrics NAME' to show details of a single entry.
        """,
)
@click.argument("name", type=str, nargs=1)
@click.pass_context
async def cli(ctx, name: str) -> None:
    """Dispatch to a server- or series-specific subcommand."""
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
    obj.metrics_cfg = obj.cfg.link.metrics
    obj.metrics_prefix = obj.metrics_cfg.prefix

    if name == "-":
        if ctx.invoked_subcommand is not None:
            raise click.BadParameter(
                "The name '-' triggers a list and precludes subcommands.",
            )
        cnt = 0
        async with obj.conn.d_walk(obj.metrics_prefix, min_depth=1, max_depth=1) as mon:
            async for p, _d in mon:
                cnt += 1
                print(p[-1], file=obj.stdout)
        if not cnt and obj.debug:
            print("no entries", file=sys.stderr)
        return

    obj.metrics_name = name
    if ctx.invoked_subcommand is None:
        try:
            data = await obj.conn.d_get(_server_path(obj))
        except KeyError:
            raise click.UsageError(
                f"Server {obj.metrics_name!r} does not exist.",
            ) from None
        yprint(data)


@cli.command("--help", hidden=True)
@click.pass_context
def _cli_help(ctx) -> None:
    """Workaround so ``cli NAME --help`` produces help text."""
    print(cli.get_help(ctx))


def _server_options(proc):
    """Add the ``add``/``set`` options for server configuration."""
    proc = click.option(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Port of this server.",
    )(proc)
    proc = click.option(
        "-h",
        "--host",
        type=str,
        default=None,
        help="Host name of this server.",
    )(proc)
    proc = click.option(
        "-b",
        "--backend",
        type=str,
        default=None,
        help="Metrics back-end driver name.",
    )(proc)
    return proc


@cli.command(short_help="Add a metrics time-series server", epilog=_backends_epilog)
@_server_options
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing server.")
@click.pass_obj
async def add(obj, backend, host, port, force) -> None:
    """Add a time-series server.

    The ``--backend`` driver option defaults to the
    ``moat.link.metrics.backend`` config value.
    """
    path = _server_path(obj)
    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError(
                f"Server {obj.metrics_name!r} already exists. Use --force or 'set'.",
            )

    srv = attrdict()
    val = attrdict(server=srv)
    val.backend = backend or obj.cfg.link.metrics.backend
    if host is not None:
        srv.host = host
    if port is not None:
        srv.port = port
    await obj.conn.d_set(path, val)


@cli.command("set", short_help="Modify a metrics time-series server", epilog=_backends_epilog)
@_server_options
@click.pass_obj
async def set_(obj, backend, host, port) -> None:
    """Modify the configuration of a metrics time-series server."""
    try:
        data = await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(f"Server {obj.metrics_name!r} does not exist.") from None
    if not isinstance(data, dict):
        raise click.UsageError(f"Server {obj.metrics_name!r} has no configuration.")

    srv = data["server"]

    if backend is not None:
        data["backend"] = backend
    if host is not None:
        srv["host"] = host
    if port is not None:
        srv["port"] = port

    await obj.conn.d_set(_server_path(obj), data)


@cli.command("delete", short_help="Delete a metrics time-series server")
@click.pass_obj
async def delete_(obj) -> None:
    """Delete a metrics time-series server and all series below it."""
    path = _server_path(obj)
    res = await obj.conn.d.delete(path, rec=True)
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
    short_help="create/show/delete an entry",
)
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def at_cli(ctx, path: Path) -> None:
    """Manage a single series entry under the server."""
    obj = ctx.obj
    try:
        await obj.conn.d_get(_server_path(obj))
    except KeyError:
        raise click.UsageError(
            "Create the server before assigning measurements to it!",
        ) from None
    obj.metrics_subpath = path
    if ctx.invoked_subcommand is None:
        await data_get(
            obj.conn,
            _server_path(obj) + path,
            recursive=False,
            out=obj.stdout,
        )


@at_cli.command("--help", hidden=True)
@click.pass_context
def _at_help(ctx) -> None:
    """Workaround so ``at PATH --help`` produces help text."""
    print(at_cli.get_help(ctx))


@at_cli.command("dump")
@click.option("-l", "--one-line", is_flag=True, help="Single line per entry")
@click.pass_obj
async def dump_at(obj, one_line: bool) -> None:
    """Emit a subtree as a list / YAML file."""
    path = _server_path(obj) + obj.metrics_subpath
    if not one_line:
        await data_get(obj.conn, path, recursive=True, out=obj.stdout)
        return
    async with obj.conn.d_walk(path) as mon:
        async for p, d in mon:
            print(f"{path + p} {d}", file=obj.stdout)


@at_cli.command("add", short_help="Add an entry")
@click.option("-f", "--force", is_flag=True, help="Allow replacing an existing entry.")
@click.option("-m", "--mode", default="gauge", help="Data series mode. Default: 'gauge'")
@click.option(
    "-a",
    "--attr",
    type=P,
    default=None,
    help="Attribute path to extract from the source value.",
)
@click.argument("source", type=P, nargs=1)
@click.argument("series", nargs=1)
@click.argument("tags", nargs=-1)
@click.pass_obj
async def add_at(obj, source, mode, attr, series, tags, force) -> None:
    """Add a series.

    \b
    PATH:   the name of this copy command. Unique path, non-empty.
    SOURCE: the element with the data. Unique path, non-empty.
    SERIES: the back-end series to write to.
    TAGS:   any number of ``name=value`` tags to use for the series.
    """
    sub: Path = obj.metrics_subpath
    if len(sub) == 0 or None in sub:
        raise click.UsageError("Path cannot be empty or contain 'None'")
    path = _server_path(obj) + sub

    if not force:
        try:
            await obj.conn.d_get(path)
        except KeyError:
            pass
        else:
            raise click.UsageError("This entry already exists. Use '--force' or 'set'.")

    if not tags:
        raise click.UsageError("You can't write to a series without tags")
    tagged: dict[str, str] = {}
    for t in tags:
        try:
            k, v = t.split("=", 1)
        except ValueError:
            raise click.UsageError("Tags must be key=value") from None
        tagged[k] = v

    val: dict[str, Any] = {
        "source": source,
        "series": series,
        "tags": tagged,
        "mode": mode,
    }
    if attr:
        val["attr"] = attr

    try:
        res: Any = await obj.conn.d_get(source)
    except KeyError:
        raise click.UsageError(f"The value at {source} does not exist.") from None
    if attr:
        try:
            for k in attr:
                res = res[k]
        except (KeyError, TypeError, IndexError):
            raise click.UsageError(
                f"The value at {source}{attr} does not exist.",
            ) from None
    if not isinstance(res, (int, float)):
        raise click.UsageError(f"The value at {source} is not a number.")

    await obj.conn.d_set(path, val)


@at_cli.command("delete")
@click.option("-r", "--recursive", is_flag=True, help="Also remove sub-entries below this path.")
@click.pass_obj
async def delete_at(obj, recursive: bool) -> None:
    """Remove a series from the metrics server.

    Without ``--recursive`` only the named entry is removed; any
    sub-entries below it are kept (they become orphans).

    The stored data is not physically deleted in the back-end, but no
    new values will be forwarded.
    """
    path = _server_path(obj) + obj.metrics_subpath
    if recursive:
        await obj.conn.d.delete(path, rec=True)
        return
    try:
        await obj.conn.d_get(path)
    except KeyError:
        raise click.UsageError("This entry doesn't exist.") from None
    await obj.conn.d_set(path, NotGiven)


@at_cli.command("set")
@attr_args
@click.pass_obj
async def set_at(obj, **kw) -> None:
    """Modify a given series."""
    if not any(kw.get(x) for x in ("vars_", "eval_", "path_")):
        return
    path = _server_path(obj) + obj.metrics_subpath
    res, _meta = await node_attr(obj, path, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@cli.command()
@click.pass_obj
async def monitor(obj) -> None:
    """Stand-alone task to monitor a single metrics server."""
    from .task import task  # noqa: PLC0415

    async with as_service(obj) as srv:
        await task(obj.conn, obj.metrics_cfg, obj.metrics_name, task_status=srv)
