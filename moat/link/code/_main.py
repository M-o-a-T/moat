"""
Command-line interface for managing stored code snippets.
"""

from __future__ import annotations

import anyio
import copy
import os
import sys

import asyncclick as click

from moat.util import NotGiven, attrdict, yformat, yload, yprint
from moat.lib.path import P, Path, PathLongener
from moat.lib.run import attr_args, process_args
from moat.link.client import Link
from moat.link.meta import MsgMeta
from moat.util.exec import run
from moat.util.module import make_proc

from collections.abc import Mapping
from typing import Any

CODE_EXEC_PATH = P("code.exec")
CODE_IS_ASYNC_PATH = P("code.is_async")
CODE_VARS_PATH = P("code.vars")
CODE_DEFAULT_PATH = P("code.default")
CODE_ROOT_PATH = P("code")

EDIT_WHOLE = "w"
EDIT_CODE = "c"
EDIT_NON_CODE = "n"
EDIT_SAVE = "s"
EDIT_ABORT = "a"


def _empty_map() -> attrdict:
    "Return an empty mapping suitable for storing a record."
    return attrdict()


def _as_map(data: Any) -> attrdict:
    """Validate and return a mapping."""
    if data is None:
        return _empty_map()
    if isinstance(data, attrdict):
        return copy.deepcopy(data)
    if isinstance(data, Mapping):
        return attrdict(copy.deepcopy(dict(data)))
    raise TypeError("Record data must be a mapping")


def _split_parent(data: Mapping[str, Any], path: Path) -> tuple[Mapping[str, Any], str] | None:
    """Follow *path* and return ``(parent,last_key)``."""
    cur: Mapping[str, Any] | Any = data
    plen = len(path)
    for idx, part in enumerate(path):
        if idx + 1 == plen:
            if isinstance(cur, Mapping):
                return cur, part
            return None
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part, NotGiven)
        if cur is NotGiven:
            return None
    return None


def _get_sub(data: Mapping[str, Any], path: Path, default: Any = NotGiven) -> Any:
    """Read a subpath from nested mappings."""
    cur: Mapping[str, Any] | Any = data
    for part in path:
        if not isinstance(cur, Mapping):
            if default is NotGiven:
                raise KeyError(path)
            return default
        cur = cur.get(part, NotGiven)
        if cur is NotGiven:
            if default is NotGiven:
                raise KeyError(path)
            return default
    return cur


def _set_sub(data: attrdict, path: Path, value: Any) -> None:
    """Write a subpath into nested mappings."""
    cur: dict[str, Any] = data
    plen = len(path)
    for idx, part in enumerate(path):
        if idx + 1 == plen:
            cur[part] = value
            return
        nxt = cur.get(part, NotGiven)
        if not isinstance(nxt, Mapping):
            nxt = attrdict()
            cur[part] = nxt
        cur = nxt


def _del_sub(data: attrdict, path: Path) -> Any:
    """Remove a subpath from nested mappings."""
    par = _split_parent(data, path)
    if par is None:
        return NotGiven
    parent, key = par
    if key not in parent:
        return NotGiven
    val = parent.pop(key)
    cur_path = list(path)
    while cur_path:
        cur_path.pop()
        if not cur_path:
            break
        par = _split_parent(data, Path.build(cur_path))
        if par is None:
            break
        parent, key = par
        sub = parent.get(key, NotGiven)
        if isinstance(sub, Mapping) and not sub:
            parent.pop(key, None)
        else:
            break
    return val


def _sanitize_vars(value: Any) -> tuple[str, ...]:
    "Normalize the configured argument names."
    if value is NotGiven or value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise TypeError("code.vars must be a list")
    return tuple(str(v) for v in value)


def _check_async_mode(value: Any) -> bool | None:
    "Normalize the configured async mode."
    if value in (NotGiven, None, True, False):
        return None if value in (None, NotGiven) else value
    raise TypeError("code.is_async must be true, false, or null")


def _check_exec_syntax(data: Mapping[str, Any], path: Path) -> None:
    """Compile the configured ``code.exec`` script."""
    code = _get_sub(data, CODE_EXEC_PATH, NotGiven)
    if code is NotGiven:
        return
    if not isinstance(code, str):
        raise TypeError("code.exec must be a string")
    vars_ = _sanitize_vars(_get_sub(data, CODE_VARS_PATH, ()))
    is_async = _check_async_mode(_get_sub(data, CODE_IS_ASYNC_PATH, None))
    make_proc(code, vars_, path + CODE_EXEC_PATH, use_async=is_async is True)


def _without_code(data: Mapping[str, Any]) -> attrdict:
    """Return a copy without the ``code`` subtree."""
    res = _as_map(data)
    _del_sub(res, CODE_ROOT_PATH)
    return res


def _merge_non_code(current: Mapping[str, Any], new_non_code: Mapping[str, Any]) -> attrdict:
    """Combine edited non-code data with the existing code subtree."""
    res = _as_map(new_non_code)
    code = _get_sub(current, CODE_ROOT_PATH, NotGiven)
    if code is not NotGiven:
        _set_sub(res, CODE_ROOT_PATH, copy.deepcopy(code))
    return res


async def _read_value(obj) -> attrdict:
    """Read the current data value."""
    try:
        data = await obj.conn.d_get(obj.path)
    except KeyError:
        return _empty_map()
    return _as_map(data)


async def _edit_text(editor: str, text: str, *, suffix: str) -> str:
    """Open a tempfile in an editor and return its content."""
    async with anyio.NamedTemporaryFile(mode="w+", suffix=suffix) as f:
        if text and not text.endswith("\n"):
            text += "\n"
        await f.write(text)
        await f.flush()
        await f.seek(0)
        await run(editor, f.name, stdin=sys.stdin, stdout=sys.stdout)
        await f.seek(0)
        return await f.read()


async def _edit_yaml(editor: str, data: Mapping[str, Any], *, suffix: str = ".yaml") -> attrdict:
    """Edit YAML content and parse the result."""
    txt = await _edit_text(editor, yformat(data, compact=False) + "\n", suffix=suffix)
    parsed = yload(txt)
    return _as_map(parsed)


def _info_line(data: Mapping[str, Any]) -> str:
    """Return an info line for a code entry."""
    info = data.get("info", NotGiven)
    if info is not NotGiven:
        return str(info)
    code = _get_sub(data, CODE_EXEC_PATH, "")
    if isinstance(code, str):
        return f"<{len(code.splitlines())} lines>"
    return "<code>"


async def _list_entries(obj, as_dict, maxdepth, mindepth, full, short):
    """List code entries in a subtree."""
    if (full or as_dict) and short:
        raise click.UsageError("'-f'/'-d' and '-s' are incompatible.")

    args = [None, None, None]
    if mindepth is not None:
        args[1] = mindepth
    if maxdepth is not None:
        args[2] = maxdepth
    while args and args[-1] is None:
        args.pop()

    pl = PathLongener(obj.path)
    out = attrdict() if as_dict is not None else None

    async with obj.conn.d.walk(obj.path, *args).stream_in() as mon:
        async for n, p, data, *_m in mon:
            path = pl.long(n, p)
            if not isinstance(data, Mapping):
                continue
            if _get_sub(data, CODE_EXEC_PATH, NotGiven) is NotGiven:
                continue

            entry = _as_map(data)
            if not full:
                _del_sub(entry, CODE_EXEC_PATH)

            if short:
                print(path, "::", _info_line(data), file=obj.stdout)
                continue

            if as_dict is not None:
                cur = out
                for pp in path:
                    cur = cur.setdefault(pp, attrdict())
                cur[as_dict] = entry
            else:
                yprint([{path: entry}], stream=obj.stdout)

    if as_dict is not None:
        yprint(out, stream=obj.stdout)


@click.group(short_help="Manage code snippets.", invoke_without_command=True)
@click.option("-m", "--meta", is_flag=True, help="Include metadata")
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path, meta):
    """
    Manage code snippets stored in MoaT-Link.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.get("port", None) is not None:
        cfg.client.port = obj.port
    obj.conn = await ctx.with_async_resource(Link(cfg, common=True))
    obj.meta = meta
    obj.path = path

    if ctx.invoked_subcommand is None:
        await _list_entries(obj, None, None, None, False, True)


@cli.command()
@click.option("-S", "--script", type=click.File(mode="w", lazy=True), help="Save the code here")
@click.pass_obj
async def get(obj, script):
    """
    Read a code entry.
    """
    if obj.meta:
        data, *meta = await obj.conn.d.get(obj.path)
        data = _as_map(data)
        out = dict(data=data, meta=MsgMeta.restore(meta).repr())
    else:
        out = await _read_value(obj)

    if script:
        if obj.meta:
            code = _del_sub(out["data"], CODE_EXEC_PATH)
        else:
            code = _del_sub(out, CODE_EXEC_PATH)
        if isinstance(code, str):
            print(code, file=script)

    yprint(out, stream=obj.stdout)


@cli.command("set")
@click.option(
    "-a/-A",
    "--async/--sync",
    "async_",
    is_flag=True,
    default=True,
    help="The code is async / sync (default: async)",
)
@click.option("-t", "--thread", is_flag=True, help="The code should run in a worker thread")
@click.option("-S", "--script", type=click.File(mode="r"), help="File with the code")
@click.option("-i", "--info", type=str, help="One-line description")
@click.option("-d", "--data", type=click.File(mode="r"), help="Load the metadata (YAML)")
@attr_args
@click.pass_obj
async def set_(obj, thread, script, data, async_, info, **kw):
    """
    Save Python code.
    """
    if thread:
        async_ = False
    elif not async_:
        async_ = None

    if data:
        msg = _as_map(yload(data))
    else:
        msg = await _read_value(obj)

    if async_ is not None or _get_sub(msg, CODE_IS_ASYNC_PATH, NotGiven) is NotGiven:
        _set_sub(msg, CODE_IS_ASYNC_PATH, async_)
    if info is not None:
        msg["info"] = info

    if script:
        _set_sub(msg, CODE_EXEC_PATH, script.read())
    elif _get_sub(msg, CODE_EXEC_PATH, NotGiven) is NotGiven:
        raise click.UsageError("Missing script")

    vs = set(_sanitize_vars(_get_sub(msg, CODE_VARS_PATH, ())))
    vd = _get_sub(msg, CODE_DEFAULT_PATH, attrdict())
    if not isinstance(vd, Mapping):
        raise click.UsageError("code.default must be a mapping")
    vd = process_args(attrdict(vd), vs=vs, **kw)
    _set_sub(msg, CODE_VARS_PATH, list(vs))
    _set_sub(msg, CODE_DEFAULT_PATH, vd)

    _check_exec_syntax(msg, obj.path)
    res = await obj.conn.d_set(obj.path, msg)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("list")
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key to use for values.",
)
@click.option("-m", "--maxdepth", type=int, default=None, help="Limit recursion depth.")
@click.option("-M", "--mindepth", type=int, default=None, help="Starting depth.")
@click.option("-f", "--full", is_flag=True, help="Print complete entries.")
@click.option("-s", "--short", is_flag=True, help="Print shortened entries.")
@click.pass_obj
async def list_(obj, as_dict, maxdepth, mindepth, full, short):
    """
    List code entries.
    """
    await _list_entries(obj, as_dict, maxdepth, mindepth, full, short)


@cli.command()
@click.pass_obj
async def delete(obj):
    """
    Remove a code entry.
    """
    try:
        res = await obj.conn.d.delete(obj.path)
    except KeyError:
        if obj.debug:
            print("Does not exist.", file=obj.stdout)
        return

    if obj.meta:
        yprint(dict(data=res[0], meta=MsgMeta.restore(res[1:]).repr()), stream=obj.stdout)
    elif obj.debug:
        print("Deleted.", file=obj.stdout)


@cli.command(short_help="Edit an entry interactively")
@click.option("-e", "--editor", type=str, default=None, help="Editor (default: $EDITOR or vi)")
@click.pass_obj
async def edit(obj, editor):
    """
    Edit a code entry interactively.

    The first edit opens the complete YAML record. Follow-up actions let you
    edit either only ``code.exec`` (``.py`` file), only non-code data
    (``.yaml`` file), or the full record.
    """
    if editor is None:
        editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))

    original = await _read_value(obj)
    current = _as_map(original)
    mode = EDIT_WHOLE

    while True:
        try:
            if mode == EDIT_WHOLE:
                current = await _edit_yaml(editor, current)
            elif mode == EDIT_CODE:
                code = _get_sub(current, CODE_EXEC_PATH, "")
                if code in (NotGiven, None):
                    code = ""
                if not isinstance(code, str):
                    raise click.UsageError("code.exec must be a string")
                code = await _edit_text(editor, code, suffix=".py")
                _set_sub(current, CODE_EXEC_PATH, code)
            elif mode == EDIT_NON_CODE:
                non_code = _without_code(current)
                non_code = await _edit_yaml(editor, non_code)
                current = _merge_non_code(current, non_code)
            else:
                raise RuntimeError(f"Invalid edit mode: {mode!r}")
            _check_exec_syntax(current, obj.path)
        except Exception as exc:
            click.echo(f"Edit failed: {exc}", err=True)
            mode = await click.prompt(
                "Continue with [w]hole, [c]ode, [n]on-code, or [a]bort?",
                type=click.Choice([EDIT_WHOLE, EDIT_CODE, EDIT_NON_CODE, EDIT_ABORT]),
                default=mode if mode in (EDIT_WHOLE, EDIT_CODE, EDIT_NON_CODE) else EDIT_WHOLE,
            )
            if mode == EDIT_ABORT:
                click.echo("Not saved.", err=True)
                return
            continue

        action = await click.prompt(
            "Next: [w]hole, [c]ode, [n]on-code, [s]ave, [a]bort?",
            type=click.Choice([EDIT_WHOLE, EDIT_CODE, EDIT_NON_CODE, EDIT_SAVE, EDIT_ABORT]),
            default=EDIT_SAVE,
        )
        if action == EDIT_ABORT:
            click.echo("Not saved.", err=True)
            return
        if action == EDIT_SAVE:
            if current == original:
                click.echo("No changes.", err=True)
                return
            _check_exec_syntax(current, obj.path)
            res = await obj.conn.d_set(obj.path, current)
            if obj.meta:
                yprint(res, stream=obj.stdout)
            else:
                click.echo("Saved.", err=True)
            return
        mode = action
