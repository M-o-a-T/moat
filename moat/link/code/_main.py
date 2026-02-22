"""
Command-line interface for managing stored code snippets.
"""

from __future__ import annotations

import os

import asyncclick as click

from moat.util import NotGiven, edit_text, edit_yaml, yload, yprint
from moat.lib.path import P, Path, PathLongener
from moat.lib.run import attr_args, process_args
from moat.link.client import Link
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code.run import make_proc
from moat.link.meta import MsgMeta

from collections.abc import Mapping
from typing import Any

EDIT_WHOLE = "w"
EDIT_CODE = "c"
EDIT_NON_CODE = "n"
EDIT_SAVE = "s"
EDIT_ABORT = "a"


def _sanitize_vars(value: Any) -> dict[str, Any]:
    "Normalize the configured argument defaults."
    if value in (NotGiven, None):
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("vars must be a mapping")
    return dict(value)


def _check_exec_syntax(data: Mapping[str, Any], path: Path) -> None:
    """Compile the configured ``code`` script."""
    code = data.get("code", NotGiven)
    if code is NotGiven:
        raise KeyError(path / "code")
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    _sanitize_vars(data.get("vars", {}))
    is_async = data.get("is_async", None)
    if is_async not in (None, True, False):
        raise TypeError("is_async must be true, false, or null")
    make_proc(code, path / "code", use_async=is_async is True)


def _info_line(data: Mapping[str, Any]) -> str:
    """Return an info line for a code entry."""
    info = data.get("info", NotGiven)
    if info is not NotGiven:
        return str(info)
    code = data.get("code", "")
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
    out = {} if as_dict is not None else None

    async with obj.conn.d.walk(obj.path, *args).stream_in() as mon:
        async for n, p, data, *_m in mon:
            path = pl.long(n, p)
            if not isinstance(data, Mapping):
                continue
            if "code" not in data:
                continue

            entry = dict(data)
            if not full:
                entry.pop("code", None)

            if short:
                print(path, "::", _info_line(data), file=obj.stdout)
                continue

            if as_dict is not None:
                cur = out
                for pp in path:
                    cur = cur.setdefault(pp, {})
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
    obj.path = CODE_EXEC_ROOT + path

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
        out = dict(data=data, meta=MsgMeta.restore(meta).repr())
    else:
        out = await obj.conn.d_get(obj.path)

    if script:
        if obj.meta:
            code = out["data"].pop("code", NotGiven)
        else:
            code = out.pop("code", NotGiven)
        if isinstance(code, str):
            print(code, file=script)

    yprint(out, stream=obj.stdout)


@cli.command("set")
@click.option("-a", "--async", "use_async", is_flag=True, help="Run this script async")
@click.option("-A", "--sync", "use_sync", is_flag=True, help="Run this script sync")
@click.option("-t", "--thread", is_flag=True, help="The code should run in a worker thread")
@click.option("-S", "--script", type=click.File(mode="r"), help="File with the code")
@click.option("-i", "--info", type=str, help="One-line description")
@click.option("-d", "--data", type=click.File(mode="r"), help="Load the metadata (YAML)")
@attr_args
@click.pass_obj
async def set_(obj, thread, script, data, use_async, use_sync, info, **kw):
    """
    Save Python code.
    """
    if use_async and use_sync:
        raise click.UsageError("--async and --sync are opposites.")
    if thread and (use_async or use_sync):
        raise click.UsageError("--thread conflicts with --async/--sync.")

    if data:
        msg = yload(data)
    else:
        msg = await obj.conn.d_get(obj.path)

    if thread:
        msg["is_async"] = False
    elif use_async:
        msg["is_async"] = True
    elif use_sync:
        msg["is_async"] = None
    if info is not None:
        msg["info"] = info

    if script:
        msg["code"] = script.read()
    elif "code" not in msg:
        raise click.UsageError("Missing script")

    vars_ = _sanitize_vars(msg.get("vars", {}))
    msg["vars"] = process_args(vars_, **kw)

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
    edit either only ``code`` (``.py`` file), only non-code data
    (``.yaml`` file), or the full record.
    """
    if editor is None:
        editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))

    try:
        original = await obj.conn.d_get(obj.path)
    except KeyError:
        try:
            original = await obj.conn.d_search(P("template") + obj.path)
        except KeyError:
            original = {"code": "return 42;\n"}
    current = dict(original)
    mode = EDIT_WHOLE

    while True:
        try:
            if mode == EDIT_WHOLE:
                current = await edit_yaml(editor, current)
            elif mode == EDIT_CODE:
                code = current.get("code", "")
                if code in (NotGiven, None):
                    code = ""
                if not isinstance(code, str):
                    raise click.UsageError("code must be a string")
                code = await edit_text(editor, code, suffix=".py")
                current["code"] = code
            elif mode == EDIT_NON_CODE:
                code = current.pop("code", NotGiven)
                try:
                    current = await edit_yaml(editor, current)
                finally:
                    if code is not NotGiven:
                        current["code"] = code
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
        else:
            mode = await click.prompt(
                "Next: [w]hole, [c]ode, [n]on-code, [s]ave, [a]bort?",
                type=click.Choice([EDIT_WHOLE, EDIT_CODE, EDIT_NON_CODE, EDIT_SAVE, EDIT_ABORT]),
                default=EDIT_SAVE,
            )
        if mode == EDIT_ABORT:
            click.echo("Not saved.", err=True)
            return
        if mode == EDIT_SAVE:
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
