"""
Command-line interface for managing stored code snippets.
"""

from __future__ import annotations

import os
import sys

import asyncclick as click
from pydantic import ValidationError

from moat.util import NotGiven, edit_text, edit_yaml, yload, yprint
from moat.lib.path import P, Path, PathLongener
from moat.lib.run import AliasedGroup, attr_args
from moat.link.client import Link
from moat.link.code import CODE_EXEC_ROOT
from moat.link.code.case import CodeTest, del_test, get_test, is_test_path, list_tests, set_test
from moat.link.code.io import path_from_file, read_snippet, split_snippet, write_snippet
from moat.link.code.run import make_proc
from moat.link.code.steps import StepSyntaxError, format_editor, parse_editor
from moat.link.code.testrun import run_tests
from moat.link.meta import MsgMeta

from collections.abc import Mapping
from typing import Any

EDIT_WHOLE = "w"
EDIT_CODE = "c"
EDIT_NON_CODE = "n"
EDIT_SAVE = "s"
EDIT_ABORT = "a"


def _sanitize_vars(value: Any) -> list[str]:
    "Normalize the declared variable-name list."
    if value in (NotGiven, None):
        return []
    if not isinstance(value, list | tuple):
        raise TypeError("vars must be a list of names")
    res: list[str] = []
    for name in value:
        if not isinstance(name, str):
            raise TypeError("vars entries must be strings")
        res.append(name)
    return res


def _sanitize_default(value: Any) -> dict[str | None, Any]:
    "Normalize the configured default values."
    if value in (NotGiven, None):
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("default must be a mapping")
    res: dict[str | None, Any] = {}
    for key, val in value.items():
        if not isinstance(key, str):
            raise TypeError("default keys must be strings")
        res[key] = val
    return res


def _check_exec_syntax(data: Mapping[str, Any], path: Path) -> None:
    """Compile the configured ``code`` script."""
    code = data.get("code", NotGiven)
    if code is NotGiven:
        raise KeyError(path / "code")
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    _sanitize_vars(data.get("vars", ()))
    _sanitize_default(data.get("default", {}))
    is_async = data.get("is_async", None)
    if is_async not in (None, True, False):
        raise TypeError("is_async must be true, false, or null")
    make_proc(code, path, use_async=is_async is True)


def _info_line(data: Mapping[str, Any]) -> str:
    """Return an info line for a code entry."""
    info = data.get("info", NotGiven)
    if info is not NotGiven:
        return str(info)
    code = data.get("code", "")
    if isinstance(code, str):
        return f"<{len(code.splitlines())} lines>"
    return "<code>"


async def _list_entries(obj, as_dict, maxdepth, mindepth, full, short) -> None:
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
    out: dict[Any, Any] | None = {} if as_dict is not None else None

    async with obj.conn.d.walk(CODE_EXEC_ROOT + obj.path, *args).stream_in() as mon:
        async for n, p, data, *_m in mon:
            path = pl.long(n, p)
            if is_test_path(path):
                continue
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
                assert out is not None
                cur: dict[Any, Any] = out
                for pp in path:
                    cur = cur.setdefault(pp, {})
                cur[as_dict] = entry
            else:
                yprint([{path: entry}], stream=obj.stdout)

    if as_dict is not None:
        yprint(out, stream=obj.stdout)


@click.group(cls=AliasedGroup, short_help="Manage code snippets.", invoke_without_command=True)
@click.option("-m", "--meta", is_flag=True, help="Include metadata")
@click.argument("path", type=P, nargs=1)
@click.pass_context
async def cli(ctx, path, meta) -> None:
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
@click.option("-r", "--recursive", is_flag=True, help="Include the test cases")
@click.pass_obj
async def get(obj, script, recursive) -> None:
    """
    Read a code entry.

    With ``-r``, the output includes the snippet's test cases (as
    ``tests``); ``import`` reads this format.
    """
    if recursive:
        if obj.meta:
            raise click.UsageError("'-m' and '-r' are incompatible.")
        out = await read_snippet(obj.conn, obj.path)
    elif obj.meta:
        data, *meta = await obj.conn.d.get(CODE_EXEC_ROOT + obj.path)
        out = dict(data=data, meta=MsgMeta.restore(meta).repr())
    else:
        out = await obj.conn.d_get(CODE_EXEC_ROOT + obj.path)

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
async def set_(obj, thread, script, data, use_async, use_sync, info, **kw) -> None:
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
        msg = await obj.conn.d_get(CODE_EXEC_ROOT + obj.path)

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

    vars_ = _sanitize_vars(msg.get("vars", ()))
    msg["vars"] = vars_
    msg["default"] = msg.get("default", {})
    msg["args"] = kw

    _check_exec_syntax(msg, obj.path)
    res = await obj.conn.d_set(CODE_EXEC_ROOT + obj.path, msg)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command("import")
@click.argument("files", type=click.Path(exists=True, dir_okay=False), nargs=-1, required=True)
@click.pass_obj
async def import_(obj, files) -> None:
    """
    Store snippets with their test cases.

    The files are in the format ``get -r`` prints. With an empty PATH
    (``:``), each file's name is the snippet's path, e.g.
    ``transform.copy.value.yaml``; otherwise PATH is used, and only one
    file may be given. Existing test cases are replaced.
    """
    if len(obj.path) and len(files) > 1:
        raise click.UsageError("Use an empty path (':') to import more than one file.")
    for fn in files:
        path = obj.path if len(obj.path) else path_from_file(fn)
        with open(fn) as f:  # noqa:ASYNC230
            data = yload(f)
        rec, _tests = split_snippet(data)
        _check_exec_syntax(rec, path)
        await write_snippet(obj.conn, path, data)
        if obj.debug:
            print(path, file=obj.stdout)


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
async def list_(obj, as_dict, maxdepth, mindepth, full, short) -> None:
    """
    List code entries.
    """
    await _list_entries(obj, as_dict, maxdepth, mindepth, full, short)


@cli.command()
@click.pass_obj
async def delete(obj) -> None:
    """
    Remove a code entry.
    """
    try:
        res = await obj.conn.d.delete(CODE_EXEC_ROOT + obj.path)
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
async def edit(obj, editor) -> None:
    """
    Edit a code entry interactively.

    The first edit opens the complete YAML record. Follow-up actions let you
    edit either only ``code`` (``.py`` file), only non-code data
    (``.yaml`` file), or the full record.
    """
    if editor is None:
        editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))

    try:
        original = await obj.conn.d_get(CODE_EXEC_ROOT + obj.path)
    except KeyError:
        try:
            original = await obj.conn.d_search(P("template") + CODE_EXEC_ROOT + obj.path)
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
            res = await obj.conn.d_set(CODE_EXEC_ROOT + obj.path, current)
            if obj.meta:
                yprint(res, stream=obj.stdout)
            else:
                click.echo("Saved.", err=True)
            return


# Test cases


def _editor_text(test: CodeTest) -> str:
    "Format a test case in the editor format."
    hdr = test.dump()
    steps = hdr.pop("steps", [])
    return format_editor(hdr, steps)


def _parse_editor_text(text: str) -> CodeTest:
    "Parse the editor format into a test case."
    hdr, steps = parse_editor(text)
    return CodeTest.model_validate(dict(hdr, steps=steps))


def _print_outcome(name: Any, out, stream, *, verbose: bool = False, keep: bool = False) -> None:
    "Print a test's outcome, its log if @verbose, and its kept test root."
    print(f"{name}: {out} ({out.duration:.2f}s)", file=stream)
    if verbose:
        for line in out.log:
            print(f"  {line}", file=stream)
    if keep and out.root is not None:
        print(f"  root: {out.root}", file=stream)


@cli.group("test", cls=AliasedGroup, invoke_without_command=True)
@click.argument("case", type=str, required=False)
@click.pass_context
async def cmd_test(ctx, case) -> None:
    """
    Manage the snippet's test cases.

    Without CASE, list them. CASE '-' means all of them (only for 'run').
    Without a subcommand, print the test case.
    """
    obj = ctx.obj
    if case is None:
        if ctx.invoked_subcommand is not None:
            raise click.UsageError("Which test case?")
        async for name, test in list_tests(obj.conn, obj.path):
            print(name, "::", test.info or f"<{len(test.steps)} steps>", file=obj.stdout)
        return
    obj.case = None if case == "-" else P(case)
    if ctx.invoked_subcommand is None:
        await ctx.invoke(case_get)


def _one_case(obj) -> Path:
    if obj.case is None:
        raise click.UsageError("This needs a single test case, not '-'.")
    return obj.case


@cmd_test.command("get")
@click.option("-e", "--editor-format", is_flag=True, help="Print in the editor's format")
@click.pass_obj
async def case_get(obj, editor_format) -> None:
    """
    Print a test case.
    """
    test = await get_test(obj.conn, obj.path, _one_case(obj))
    if editor_format:
        print(_editor_text(test), end="", file=obj.stdout)
    else:
        yprint(test.dump(), stream=obj.stdout)


@cmd_test.command("set")
@click.option(
    "-d", "--data", type=click.File(mode="r"), required=True, help="The test case (YAML)"
)
@click.option("-e", "--editor-format", is_flag=True, help="The file uses the editor's format")
@click.pass_obj
async def case_set(obj, data, editor_format) -> None:
    """
    Store a test case.
    """
    case = _one_case(obj)
    if editor_format:
        test = _parse_editor_text(data.read())
    else:
        test = CodeTest.model_validate(yload(data))
    await set_test(obj.conn, obj.path, case, test)


@cmd_test.command("delete")
@click.pass_obj
async def case_delete(obj) -> None:
    """
    Delete a test case.
    """
    try:
        await del_test(obj.conn, obj.path, _one_case(obj))
    except KeyError:
        if obj.debug:
            print("Does not exist.", file=obj.stdout)
    else:
        if obj.debug:
            print("Deleted.", file=obj.stdout)


@cmd_test.command("edit")
@click.option("-e", "--editor", type=str, default=None, help="Editor (default: $EDITOR or vi)")
@click.pass_obj
async def case_edit(obj, editor) -> None:
    """
    Edit a test case.

    The header (info, timeout, data, args) is a YAML document; after a
    '---' line, each line is one action.
    """
    case = _one_case(obj)
    if editor is None:
        editor = os.environ.get("VISUAL", os.environ.get("EDITOR", "vi"))

    try:
        original = await get_test(obj.conn, obj.path, case)
    except KeyError:
        original = CodeTest(steps=[["start"]])
    content = orig_content = _editor_text(original)

    while True:
        content = await edit_text(editor, content, suffix=".yaml")
        try:
            test = _parse_editor_text(content)
        except (StepSyntaxError, ValidationError) as exc:
            click.echo(f"Error: {exc}", err=True)
            choice = await click.prompt(
                "Re-open with [o]riginal, [e]dited content, or [q]uit?",
                type=click.Choice(["o", "e", "q"], case_sensitive=False),
                default="e",
            )
            if choice == "q":
                click.echo("Not saved.", err=True)
                return
            if choice == "o":
                content = orig_content
            continue
        break

    if test == original:
        click.echo("No changes.", err=True)
        return
    await set_test(obj.conn, obj.path, case, test)
    click.echo("Saved.", err=True)


@cmd_test.command("run")
@click.option("-k", "--keep", is_flag=True, help="Don't delete the test root afterwards")
@click.option("-v", "--verbose", is_flag=True, help="Show the test's log")
@click.option("-j", "--jobs", type=int, default=None, help="Run at most N tests at a time")
@click.pass_obj
async def case_run(obj, keep, verbose, jobs) -> None:
    """
    Run a test case, or all of them ('-').

    Exits with code 1 if a test fails.
    """
    if obj.case is None:
        tests = [(name, obj.path, test) async for name, test in list_tests(obj.conn, obj.path)]
        if not tests:
            raise click.UsageError("This snippet has no tests.")
    else:
        tests = [(obj.case, obj.path, await get_test(obj.conn, obj.path, obj.case))]

    res = await run_tests(
        obj.conn,
        tests,
        limit=jobs,
        keep=keep,
        log_stream=obj.stdout if verbose else None,
    )
    for name, out in res:
        _print_outcome(name, out, obj.stdout, verbose=verbose, keep=keep)
    if not all(out.ok for _, out in res):
        sys.exit(1)


@cli.command("test-all")
@click.option("-j", "--jobs", type=int, default=None, help="Run at most N tests at a time")
@click.option("-v", "--verbose", is_flag=True, help="Show every test's outcome")
@click.pass_obj
async def cmd_test_all(obj, jobs, verbose) -> None:
    """
    Run the tests of every snippet below PATH.

    Prints a summary per snippet, and the failed tests. Exits with code 1
    if a test fails.
    """
    tests = []
    async with obj.conn.d_walk(CODE_EXEC_ROOT + obj.path) as mon:
        async for path, data in mon:
            if not is_test_path(path):
                continue
            i = path.index(None)
            code, name = obj.path + path[:i], Path.build(path[i + 1 :])
            if not len(name):
                continue
            tests.append(((code, name), code, CodeTest.model_validate(data)))
    if not tests:
        print("No tests.", file=obj.stdout)
        return

    res = await run_tests(obj.conn, tests, limit=jobs)

    summary: dict[Path, list[int]] = {}
    for (code, name), out in res:
        summary.setdefault(code, [0, 0])[not out.ok] += 1
        if verbose or not out.ok:
            _print_outcome(f"{code} {name}", out, obj.stdout, verbose=verbose)
    for code, (good, bad) in summary.items():
        print(f"{code}: {good} passed, {bad} failed", file=obj.stdout)
    if any(bad for _, bad in summary.values()):
        sys.exit(1)
