# command line interface  # noqa: D100
from __future__ import annotations

import sys

import asyncclick as click

from moat.util import yprint
from moat.lib.path import P
from moat.lib.run import AliasedGroup, attr_args
from moat.link._data import data_get, node_attr
from moat.link.client import Link
from moat.link.meta import MsgMeta


def _conv_prefix(obj):
    """Return the configured conv prefix (default ``conv``)."""
    return obj.cfg["link"].get("conv", {}).get("prefix", P("conv"))


async def _ensure_exists(conn, path, what):
    try:
        await conn.d_get(path)
    except KeyError:
        raise click.UsageError(f"{what} {path!s} does not exist.") from None


async def _ensure_absent(conn, path, what):
    try:
        await conn.d_get(path)
    except KeyError:
        return
    raise click.UsageError(f"{what} {path!s} already exists.")


async def _do_get(obj):
    """Show the entry at ``obj.path``."""
    await data_get(obj.conn, obj.path, meta=obj.meta, recursive=False, out=obj.stdout)


async def _do_set(obj, kw):
    """Update the entry at ``obj.path`` via :func:`node_attr`.

    Requires the entry to exist; use ``add`` to create one.
    """
    await _ensure_exists(obj.conn, obj.path, "Entry")
    res, meta = await node_attr(obj, obj.path, **kw)
    if obj.meta:
        out = {"value": res, "meta": meta.dump() if meta is not None else None}
        yprint(out, stream=obj.stdout)


async def _do_add(obj, codec, *, require_parent):
    """Create the entry at ``obj.path`` with ``{codec: CODEC}``.

    Args:
        require_parent: also assert that the immediate parent of
            ``obj.path`` (saved as ``obj.parent_path``) exists.
    """
    if require_parent and obj.parent_path is not None:
        await _ensure_exists(obj.conn, obj.parent_path, "Parent")
    await _ensure_absent(obj.conn, obj.path, "Entry")
    res = await obj.conn.d_set(obj.path, {"codec": codec}, meta=obj.meta)
    if obj.meta:
        yprint(res, stream=obj.stdout)


async def _do_delete(obj, recursive):
    """Delete ``obj.path``; optionally also its subtree."""
    args = {"rec": True} if recursive else {}
    res = await obj.conn.d.delete(obj.path, **args)
    if not len(res):
        return
    val = res[0]
    if val is None:
        return
    if isinstance(val, (list, tuple)) and val:
        dv, *m = val
        meta = MsgMeta.restore(list(m)) if m else None
    else:
        dv, meta = val, None
    if obj.meta:
        out = {"data": dv, "meta": meta.repr() if meta is not None else None}
    else:
        out = dv
    yprint(out, stream=obj.stdout)


async def _do_list(obj):
    """List all paths at and below ``obj.path`` with their codec."""
    seen = False
    async with obj.conn.d_walk(obj.path) as mon:
        async for p, d in mon:
            seen = True
            try:
                print(f"{obj.path + p} : {d['codec']}", file=obj.stdout)
            except (KeyError, TypeError):
                print(f"{obj.path + p}", file=obj.stdout)
    if not seen and obj.debug:
        print("- no entries.", file=sys.stderr)


@click.group(
    cls=AliasedGroup,
    short_help="Manage codec/path mappings.",
    invoke_without_command=True,
)
@click.option("-m", "--meta", is_flag=True, help="include metadata")
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path, meta):
    """
    Manage codec/path mappings (the ``conv`` subtree).

    The ``PATH`` argument is the converter name (relative to the configured
    ``link.conv.prefix``, default ``conv``).  Use the ``at`` sub-command
    to operate on sub-paths below it.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.meta = meta
    if not len(path):
        raise click.UsageError("PATH must not be empty.")
    obj.parent_path = None
    obj.path = _conv_prefix(obj) + path
    if ctx.invoked_subcommand is None:
        await _do_get(obj)


@cli.command()
@click.pass_obj
async def get(obj):
    """Read this conv entry."""
    await _do_get(obj)


@cli.command("set", short_help="Update entry attributes")
@attr_args
@click.pass_obj
async def set_(obj, **kw):
    """Update the attributes of this conv entry."""
    await _do_set(obj, kw)


@cli.command()
@click.argument("codec", type=P, nargs=1)
@click.pass_obj
async def add(obj, codec):
    """Create this conv entry with ``codec=CODEC`` as the default.

    Fails if the entry already exists.
    """
    await _do_add(obj, codec, require_parent=False)


@cli.command()
@click.pass_obj
async def delete(obj):
    """Delete this entry and its entire subtree."""
    await _do_delete(obj, recursive=True)


@cli.command("list")
@click.pass_obj
async def list_(obj):
    """List all paths at and below this conv entry, with their codec."""
    await _do_list(obj)


@cli.group(
    cls=AliasedGroup,
    short_help="Operate on a sub-path of this conv entry.",
    invoke_without_command=True,
)
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def at(ctx, path):
    """
    Operate on ``conv.A.B``.

    ``PATH`` is appended to the outer conv entry's path.  Subcommands
    behave like the outer ones, except that ``delete`` is non-recursive
    by default (pass ``-r`` to remove the whole subtree).
    """
    obj = ctx.obj
    if not len(path):
        raise click.UsageError("Sub-PATH must not be empty.")
    obj.parent_path = obj.path
    obj.path = obj.path + path
    if ctx.invoked_subcommand is None:
        await _do_get(obj)


@at.command("get")
@click.pass_obj
async def at_get(obj):
    """Read this sub-entry."""
    await _do_get(obj)


@at.command("set", short_help="Update sub-entry attributes")
@attr_args
@click.pass_obj
async def at_set(obj, **kw):
    """Update the attributes of this sub-entry."""
    await _do_set(obj, kw)


@at.command("add")
@click.argument("codec", type=P, nargs=1)
@click.pass_obj
async def at_add(obj, codec):
    """Create this sub-entry with ``codec=CODEC``.

    Fails if the outer conv entry does not exist, or if this sub-entry
    already exists.
    """
    await _do_add(obj, codec, require_parent=True)


@at.command("delete")
@click.option("-r", "--recursive", is_flag=True, help="Also remove children.")
@click.pass_obj
async def at_delete(obj, recursive):
    """Delete this sub-entry.

    By default, only the entry itself is removed; pass ``-r`` to drop
    everything below it as well.
    """
    await _do_delete(obj, recursive=recursive)


@at.command("list")
@click.pass_obj
async def at_list(obj):
    """List all paths at and below this sub-entry, with their codec."""
    await _do_list(obj)
