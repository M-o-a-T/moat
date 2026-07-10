# command line interface  # noqa: D100
from __future__ import annotations

import anyio
import os
import sys
import time
from contextlib import nullcontext, suppress

import asyncclick as click

from moat.util import (
    MsgReader,
    NotGiven,
    combine_dict,
    edit_text,
    help_preserve_blocks,
    yformat,
    yload,
    yprint,
)
from moat.lib.path import P, Path, Root
from moat.lib.run import AliasedGroup, attr_args, process_args
from moat.link._data import data_get
from moat.link.client import Link
from moat.link.meta import MsgMeta


def _encode_dict_entry(path: Path, data, meta: MsgMeta | None) -> dict:
    """Encode one dump entry using mapping format."""

    res = {"_path": str(path)}
    if meta is not None:
        res["_meta"] = meta.dump()
    if (
        isinstance(data, dict)
        and "_path" not in data
        and "_meta" not in data
        and "_value" not in data
        and not any(isinstance(key, str) and key.startswith("_") for key in data)
    ):
        res.update(data)
    else:
        res["_value"] = data
    return res


def _decode_meta(data) -> MsgMeta | None:
    """Decode metadata from one dump entry."""

    if data is None:
        return None
    if isinstance(data, MsgMeta):
        return data
    if isinstance(data, list | tuple):
        return MsgMeta.restore(list(data))
    if isinstance(data, dict):
        try:
            return MsgMeta(**{
                k: v for k, v in data.items() if not (isinstance(k, str) and k.startswith("_"))
            })
        except ValueError as exc:
            raise click.UsageError(
                "Metadata mappings need at least origin and timestamp."
            ) from exc
    raise click.UsageError("Metadata must be a MsgMeta, list, tuple, mapping, or null.")


async def _dump_data(obj, as_dict: bool = False) -> None:
    """Emit subtree entries as YAML docs without human-formatted timestamps."""
    include_meta = getattr(obj, "meta", False)

    async with obj.conn.d_watch(
        obj.path,
        state=True,
        meta=include_meta,
        subtree=True,
    ) as mon:
        async for pdm in mon:
            if include_meta:
                p, d, m = pdm
            else:
                p, d = pdm
                m = None
            with suppress(BrokenPipeError):
                if as_dict:
                    yprint(_encode_dict_entry(obj.path + p, d, m), stream=obj.stdout)
                else:
                    if m is None:
                        yprint([p, d], stream=obj.stdout)
                    else:
                        yprint([p, d, *m.dump()], stream=obj.stdout)
                print("---", file=obj.stdout)
                obj.stdout.flush()


def _write_result(res) -> bool | None:
    """Convert `d.set` response to write status."""

    if isinstance(res, bool) or res is None:
        return res
    return res[0]


async def _load_data(obj, infile: str, force: bool) -> None:
    """Load subtree entries from YAML docs."""

    path = "/dev/stdin" if infile == "-" else infile
    async with MsgReader(path=path, codec="yaml") as reader:
        async for msg in reader:
            if isinstance(msg, dict):
                if "path" in msg and "value" in msg:
                    try:
                        p = msg["path"]
                        d = msg["value"]
                    except KeyError as exc:
                        raise click.UsageError("Dict entries need 'path' and 'value'.") from exc
                    m = msg.get("meta")
                else:
                    try:
                        p = msg["_path"]
                    except KeyError as exc:
                        raise click.UsageError(
                            "Dict entries need either path/value or _path/_value layout."
                        ) from exc
                    if "_value" in msg:
                        d = msg["_value"]
                    else:
                        d = {
                            k: v
                            for k, v in msg.items()
                            if not (isinstance(k, str) and k.startswith("_"))
                        }
                    m = msg.get("_meta")
            else:
                if not isinstance(msg, list | tuple) or len(msg) < 2:
                    raise click.UsageError(
                        "Entries must be [path, value] or [path, value, meta...]."
                    )
                p, d, *m = msg
                if len(m) == 0:
                    m = None
                elif len(m) == 1 and isinstance(m[0], MsgMeta | list | tuple | dict):
                    m = m[0]

            p = P(p) if isinstance(p, str) else Path.build(p)
            m = _decode_meta(m)
            p = obj.path + p

            if force:
                ts = time.time()
                res = _write_result(await obj.conn.d.set(p, d, m))
                if res is False:
                    if m is None:
                        m2 = MsgMeta(origin=obj.conn.name, timestamp=ts)
                    else:
                        m2 = MsgMeta.restore(list(m.a), dict(m.kw))
                        m2.timestamp = ts
                    await obj.conn.d.set(p, d, m2)
            else:
                await obj.conn.d.set(p, d, m)


@click.group(cls=AliasedGroup, short_help="Manage data.", invoke_without_command=True)  # pylint: disable=undefined-variable
@click.option("-m", "--meta", is_flag=True, help="include metadata")
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path, meta):
    """
    This subcommand accesses the data stored in the MoaT-Link server.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.meta = meta
    if ctx.invoked_subcommand is None:
        await data_get(obj.conn, path, meta=obj.meta, out=obj.stdout, recursive=False)
    else:
        obj.path = path


@cli.command()
@click.option("-r", "--recursive", is_flag=True, help="Read a complete subtree")
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use "
    "for values. Default: return as list",
)
@click.option(
    "-n",
    "--maxdepth",
    type=int,
    default=None,
    help="Limit recursion depth. Default: whole tree",
)
@click.option(
    "-N",
    "--mindepth",
    type=int,
    default=None,
    help="Starting depth. Default: root",
)
@click.option("-e", "--empty", is_flag=True, help="Include empty nodes")
@click.option("-R", "--raw", is_flag=True, help="Print string values without quotes etc.")
@click.option("-D", "--add-date", is_flag=True, help="Add *_date entries")
@click.pass_obj
async def get(obj, **k):
    """
    Read a MoaT-Link value.

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """

    await data_get(obj.conn, obj.path, meta=obj.meta, **k)


@cli.command("list")
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use "
    "for values. Default: return as list",
)
@click.option(
    "-N",
    "--maxdepth",
    type=int,
    default=1,
    help="Limit recursion depth. Default: 1 (single layer).",
)
@click.option(
    "-N",
    "--mindepth",
    type=int,
    default=1,
    help="Starting depth. Default: 1 (single layer).",
)
@click.pass_obj
async def list_(obj, **k):
    """
    List MoaT-Link values.

    This is like "get" but with "--mindepth=1 --maxdepth=1 --recursive --empty"

    If you read a sub-tree recursively, be aware that the whole subtree
    will be read before anything is printed. Use the "watch --state" subcommand
    for incremental output.
    """

    k["recursive"] = True
    k["raw"] = True
    k["empty"] = True
    await data_get(obj.conn, obj.path, meta=obj.meta, **k)


@cli.command("set", short_help="Add or update an entry")
@attr_args
@click.option("-r", "--retain", is_flag=True, help="Retain the result")
@click.option("-f", "--force", is_flag=True, help="Ignore existing data")
@click.option("-o", "--one-shot", "one", is_flag=True, help="Do not retain the result")
@click.option("-y", "--yaml", is_flag=True, help="read YAML data from stdin")
@click.pass_obj
async def set_(obj, yaml, one, retain, force, **kw):
    """
    Store a value at some MoaT-Link position.

    Use '--set : VALUE' if you want to set a non-dict element.
    """
    if one:
        if kw.get("retain", False):
            raise click.UsageError("--retain and --one-shot are opposites.")
        kw["retain"] = False
    d = {}
    if not force:
        with suppress(KeyError):
            d = await obj.conn.d_get(obj.path)
    if yaml:
        d = combine_dict(yload(sys.stdin), d)
    d = process_args(d, **kw)
    res = await obj.conn.d_set(
        obj.path, d, retain=True if retain else False if one else None, meta=obj.meta
    )
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command(short_help="Edit an entry interactively")
@click.option("-y", "--yes", is_flag=True, help="Save without asking")
@click.option("-e", "--editor", type=str, default=None, help="Editor (default: $EDITOR or vi)")
@click.pass_obj
async def edit(obj, yes, editor):
    """
    Edit a MoaT-Link value interactively.

    Opens the current value in an editor (YAML format). After editing,
    parses the result and saves it back.
    """
    try:
        data = await obj.conn.d_get(obj.path)
    except KeyError:
        try:
            data = await obj.conn.d_search(P("template") + obj.path)
        except KeyError:
            data = {}

    if editor is None:
        editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))

    content = yformat(data, compact=False) + "\n"

    while True:
        edited_content = await edit_text(editor, content, suffix=".yaml")

        try:
            new_data = yload(edited_content)
        except Exception as e:
            click.echo(f"YAML parse error: {e}", err=True)
            choice = await click.prompt(
                "Re-open with [o]riginal, [e]dited content, or [q]uit?",
                type=click.Choice(["o", "e", "q"], case_sensitive=False),
                default="e",
            )
            if choice == "q":
                click.echo("Not saved.", err=True)
                return
            if choice == "o":
                content = yformat(data, compact=False) + "\n"
            else:
                content = edited_content
            continue

        if new_data == data:
            click.echo("No changes.", err=True)
            return

        if not yes:
            # TODO this still blocks
            if not click.confirm("Save changes?", default=True):
                click.echo("Not saved.", err=True)
                return

        # Save
        res = await obj.conn.d_set(obj.path, new_data, meta=obj.meta)
        if obj.meta:
            yprint(res, stream=obj.stdout)
        else:
            click.echo("Saved.", err=True)
        return


@cli.command(short_help="Delete an entry / subtree")
@click.option(
    "-b",
    "--before",
    type=float,
    help="Don't delete entries created after this timestamp",
)
@click.option("-r", "--recursive", is_flag=True, help="Delete a complete subtree")
@click.option(
    "-s",
    "--sub",
    is_flag=True,
    help="Delete the subtree below the entry but keep the entry itself",
)
@click.option("-m", "--mqtt", is_flag=True, help="Delete via MQTT message")
@click.pass_obj
async def delete(obj, before, recursive, sub, mqtt):
    """
    Delete an entry, or a subtree.

    Non-recursively deleting an entry with children does not
    affect the child entries.

    The root entry cannot be deleted.
    """
    if recursive and sub:
        raise click.UsageError("--recursive and --sub are mutually exclusive")
    if mqtt:
        if recursive or sub or before:
            raise click.UsageError("--mqtt and --recursive/--sub/--before don't like each other")
        await obj.conn.send(Root.get() + obj.path, NotGiven, retain=True)
        return

    args = {}
    if recursive:
        args["rec"] = recursive
    if sub:
        args["sub"] = sub
    if before:
        args["ts"] = before

    res = await obj.conn.d.delete(obj.path, **args)
    if obj.meta:
        res = dict(data=res[0], meta=MsgMeta.restore(res[1:]).repr())
    else:
        res = res[0]
    yprint(res, stream=obj.stdout)


@cli.command()
@click.option("-m", "--mode", type=str, help="Retrieval mode", default="s", metavar="MODE")
@click.option("-M", "--mark", is_flag=True, help="Insert static-part-done flag")
@click.option("-o", "--only", is_flag=True, help="Value only, nothing fancy.")
@click.option("-s", "--subtree", is_flag=True, help="Read the whole tree.")
@click.option("-p", "--path-only", is_flag=True, help="Value only, nothing fancy.")
@click.option("-D", "--add-date", is_flag=True, help="Add *_date entries")
@click.option("-i", "--ignore", multiple=True, type=P, help="Skip this (sub)tree")
@click.option("-n", "--mindepth", type=int, help="Minimum path length")
@click.option("-N", "--maxdepth", type=int, help="Maximum path length")
@click.option("-a", "--maxage", type=int, help="Skip entries older than N seconds")
@click.option("-t", "--timeout", type=int, help="Stop reading after N seconds")
@click.pass_obj
@help_preserve_blocks
async def monitor(
    obj,
    mode,
    only,
    path_only,
    add_date,  # noqa: ARG001
    ignore,
    mark,
    subtree,
    mindepth,
    maxdepth,
    maxage,
    timeout,
):
    """Monitor a MoaT-Link subtree.

    MODE can be:
    * c  current   read current data from the server
    * u  update    read updates from MQTT
    * s  stream    current plus updates
    * m  mqtt      subscribe to the MQTT stream, including retained data
    """

    match mode:
        case "c" | "current":
            state = True
        case "u" | "update":
            state = False
        case "s" | "stream":
            state = None
        case "m" | "mqtt":
            state = NotGiven
        case _:
            raise click.UsageError("Mode must be current|update|stream|mqtt")
    if mark and state is not None:
        raise click.UsageError("You can only add a mark in Stream mode")

    def pm(p):
        for ip in ignore:
            if len(p) >= len(ip) and p[: len(ip)] == ip:
                return True
        return False

    with anyio.move_on_after(timeout) if timeout else nullcontext():
        async with obj.conn.d_watch(
            obj.path,
            state=state,
            mark=mark,
            meta=True,
            subtree=subtree,
            max_length=maxdepth,
            min_length=mindepth,
            age=maxage,
        ) as mon:
            async for pdm in mon:
                if pdm is None:
                    res = "*** Snapshot data ends ***"
                else:
                    if subtree:
                        p, d, m = pdm
                        if pm(p):
                            continue
                    else:
                        d, m = pdm

                    if only:
                        res = d
                    elif path_only:
                        res = p
                    elif obj.meta:
                        res = [p, d, m]
                    else:
                        res = [p, d]
                with suppress(BrokenPipeError):
                    yprint(res, stream=obj.stdout)
                    print("---", file=obj.stdout)
                    obj.stdout.flush()


@cli.command()
@click.option("-d", "--dict", "as_dict", is_flag=True, help="Write dict-based dump docs.")
@click.pass_obj
async def dump(obj, as_dict):
    """
    Dump one subtree as YAML docs.

    Metadata is included iff the top-level ``-m/--meta`` flag is set.
    This is otherwise equivalent to ``monitor -m c -s``.
    """
    await _dump_data(obj, as_dict=as_dict)


@cli.command()
@click.option("-i", "--infile", type=click.Path(), default="-", help="File to read.")
@click.option("-f", "--force", is_flag=True, help="Overwrite entries regardless of timestamp.")
@click.pass_obj
async def load(obj, infile, force):
    """
    Load path+data+metadata tuples from YAML docs into a subtree.
    """
    await _load_data(obj, infile, force)


async def _import_data(
    obj,
    infile: str,
    *,
    as_dict: str | None,
) -> None:
    """Import legacy MoaT-KV ``data … get -r [-d KEY]`` output.

    The whole input file is parsed as a single YAML document.

    Args:
        obj: the command-context object (provides ``conn`` and ``path``).
        infile: source file name, or ``-`` for stdin.
        as_dict: if given, parse the input as the nested-dict form
            emitted by ``mt kv data … get -r -d KEY`` (with KEY marking
            value leaves). If `None`, parse the list form emitted by
            ``mt kv data … get -r``.

    Raises:
        click.UsageError: if the input does not match the expected
            shape.
    """
    path = "/dev/stdin" if infile == "-" else infile
    async with await anyio.open_file(path, "rb") as f:
        raw = await f.read()
    try:
        doc = yload(raw.decode("utf-8", "surrogateescape"))
    except Exception as exc:
        raise click.UsageError(f"Cannot parse YAML input: {exc}") from exc

    if as_dict is None:
        await _import_legacy_list(obj, doc)
    else:
        await _import_legacy_dict(obj, doc, as_dict)


def _as_path(p) -> Path:
    """Coerce a YAML-decoded path representation to :class:`Path`."""
    if isinstance(p, Path):
        return p
    if isinstance(p, str):
        return P(p)
    if isinstance(p, (list, tuple)):
        return Path.build(p)
    raise click.UsageError(f"Cannot interpret {p!r} as a path.")


async def _import_legacy_list(obj, doc) -> None:
    """Import the list-of-singleton-dicts form from ``mt kv data … get -r``."""
    if not isinstance(doc, list):
        raise click.UsageError(
            "--legacy expects the YAML list emitted by 'mt kv data … get -r'.",
        )
    for item in doc:
        if not isinstance(item, dict) or len(item) != 1:
            raise click.UsageError(
                "--legacy expects each list entry to be a single {path: value} mapping.",
            )
        p, v = next(iter(item.items()))
        await obj.conn.d_set(obj.path + _as_path(p), v)


async def _import_legacy_dict(obj, doc, as_dict: str) -> None:
    """Import the nested-dict form from ``mt kv data … get -r -d KEY``."""
    if not isinstance(doc, dict):
        raise click.UsageError(
            "--as-dict expects the YAML mapping emitted by 'mt kv data … get -r -d KEY'.",
        )

    async def walk(prefix: Path, node: dict) -> None:
        for k, v in node.items():
            if k == as_dict:
                await obj.conn.d_set(obj.path + prefix, v)
            elif isinstance(v, dict):
                await walk(prefix + Path.build((k,)), v)

    await walk(Path(), doc)


@cli.command("import", short_help="Import data from a MoaT-KV dump")
@click.option("-i", "--infile", type=click.Path(), default="-", help="File to read.")
@click.option(
    "--legacy",
    is_flag=True,
    help="Input is from 'mt kv data … get -r' (a YAML list).",
)
@click.option(
    "-d",
    "--as-dict",
    "as_dict",
    default=None,
    metavar="KEY",
    help="Input is from 'mt kv data … get -r -d KEY' (a nested mapping).",
)
@click.pass_obj
async def import_(obj, infile: str, legacy: bool, as_dict: str | None) -> None:
    """Import data from a ``mt kv data … get -r`` dump.

    Exactly one of ``--legacy`` or ``--as-dict`` must be given to
    indicate which on-disk format the input is in. Imported values are
    written below the current ``PATH``.
    """
    if legacy == (as_dict is not None):
        raise click.UsageError(
            "Pass exactly one of --legacy or --as-dict to select the input format.",
        )
    await _import_data(obj, infile, as_dict=as_dict)


@cli.command()
@click.option("-i", "--infile", type=click.Path(), help="File to read.")
@click.option("-C", "--codec", type=str, default="yaml", help="Codec to use (default: yaml).")
@click.pass_obj
async def update(obj, infile, codec):
    """
    Copy a list of updates from a file to a MoaT-Link subtree
    """
    async with MsgReader(path="/dev/stdin" if infile == "-" else infile, codec=codec) as reader:
        async for msg in reader:
            if isinstance(msg, dict):
                p = msg["path"]
                v = msg["value"]
            else:
                p, v, *_m = msg
            await obj.conn.d_set(obj.path + p, v)
