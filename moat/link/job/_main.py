"""
Command-line interface for ``moat link job``.

Behaviour mirrors ``moat kv job``: the same subcommands operate on a
subtree of stored job records and a parallel subtree of dynamic state.
"""

from __future__ import annotations

import anyio
import sys
import time
from functools import partial

import asyncclick as click

from moat.util import attrdict, yprint
from moat.lib.path import P, Path
from moat.lib.run import AliasedGroup, attr_args, process_args
from moat.link._data import add_dates, data_get
from moat.link.client import Link

from .runner import AllJobRunner, AnyJobRunner, JobRunner, SingleJobRunner, debug_run

from typing import Any

__all__ = ["cli"]


def _resolve_runner(node: str | None, group: str | None) -> tuple[type[JobRunner], tuple]:
    """Pick a runner class and base subpath from the ``-n``/``-g`` options."""
    if group is None:
        group = "default"
    if group == "-":
        if node is not None:
            raise click.UsageError("'-g -' doesn't make sense with '-n'")
        return SingleJobRunner, (None,)
    if not node:
        return AnyJobRunner, (group,)
    if node == "-":
        return AllJobRunner, (group,)
    return SingleJobRunner, (node, group)


@click.group(cls=AliasedGroup, invoke_without_command=False)
@click.option(
    "-n",
    "--node",
    help="Node to run on. Empty: any one node, '-': all nodes.",
)
@click.option("-g", "--group", help="Job group (default: 'default').")
@click.pass_context
async def cli(ctx: click.Context, node: str | None, group: str | None) -> None:
    """Run code stored in MoaT-Link.

    \b
    The ``-n`` option selects coordination:
    -n -     Jobs running on every host.
    -n XXX   Jobs running on the host named XXX.
    (no -n)  Jobs running on any single host (cluster-shared).

    The default group is ``default``.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    if obj.get("port", None) is not None:
        cfg.client.port = obj.port

    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None)),
    )

    obj.runner_cls, sub = _resolve_runner(node, group)
    job_cfg = cfg["job"]
    obj.job_cfg = job_cfg
    obj.subpath = Path.build(job_cfg["sub"][obj.runner_cls.SUB]) + Path.build(sub)
    obj.path = Path.build(job_cfg["prefix"]) + obj.subpath
    obj.statepath = Path.build(job_cfg["state"]) + obj.subpath


@cli.group("at", short_help="Path of the job to operate on.", invoke_without_command=True)
@click.argument("path", nargs=1, type=P)
@click.pass_context
async def at_cli(ctx: click.Context, path: Path) -> None:
    """Add, list, modify, or delete jobs at/under this path."""
    obj = ctx.obj
    obj.jobpath = path
    if ctx.invoked_subcommand is None:
        try:
            res = await obj.conn.d_get(obj.path + path)
        except KeyError:
            res = None
        yprint(res, stream=obj.stdout)


@cli.command("info")
@click.pass_obj
async def info_(obj: attrdict) -> None:
    """List groups/hosts with jobs.

    \b
    (none)    list groups with jobs for any host
    -n -      list groups with jobs for all hosts
    -g -      list hosts that have specific jobs
    -n XXX    list groups with jobs for a specific host
    """
    path = Path.build(obj.path[:-1])
    seen: set[Any] = set()
    async with obj.conn.d.walk(path, None, 1).stream_in() as mon:
        async for r in mon:
            _, p, *_rest = r
            if not p:
                continue
            head = p[0]
            if head in seen:
                continue
            seen.add(head)
            print(head, file=obj.stdout)


@at_cli.command("path")
@click.pass_obj
async def path__(obj: attrdict) -> None:
    """Emit the full link path of this job's command and state entries.

    The state entry is managed by the runner and must not be written
    directly. Updating the command entry cancels any currently-running
    code for that job.
    """
    res = {"command": obj.path + obj.jobpath, "state": obj.statepath + obj.jobpath}
    yprint(res, stream=obj.stdout)


@cli.command("run")
@click.option(
    "-n",
    "--nodes",
    type=int,
    default=0,
    help="Cluster size (ignored for single-node runners).",
)
@click.pass_obj
async def run(obj: attrdict, nodes: int) -> None:
    """Start the runner.

    This command does not return until cancelled. It runs eligible jobs
    until interrupted.
    """
    from moat.link.announce import as_service  # noqa: PLC0415

    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")
    if nodes and obj.runner_cls is SingleJobRunner:
        raise click.UsageError("A single-site runner doesn't have a size.")

    runner_cls: type[JobRunner] = obj.runner_cls
    runner = runner_cls(obj.conn, obj.job_cfg, obj.subpath, nodes=nodes)
    async with as_service(obj) as srv, runner.run():
        srv.set()
        await anyio.sleep_forever()


async def _state_fix(
    obj: attrdict,
    state_path: Path | None,
    state_only: bool,
    path_prefix: Path | None,
    r: Any,
) -> Any:
    """Augment a job record with its current state and optional dates."""
    try:
        val = r.value
    except AttributeError:
        return r
    if state_path is not None:
        try:
            rs = await obj.conn.d_get(state_path + r.path)
        except KeyError:
            rs = None
        if state_only:
            r.value = rs
        elif rs is not None:
            val["state"] = rs
            add_dates(rs)
    if not state_only:
        if path_prefix is not None:
            r.path = path_prefix + r.path
        add_dates(val)
    return r


@at_cli.command("list")
@click.option("-s", "--state", is_flag=True, help="Add state data.")
@click.option("-S", "--state-only", is_flag=True, help="Only output state data.")
@click.option("-t", "--table", is_flag=True, help="One-line output.")
@click.option(
    "-d",
    "--as-dict",
    default=None,
    help="Structure as dictionary. The argument is the key used for values.",
)
@click.pass_obj
async def list_(
    obj: attrdict,
    state: bool,
    state_only: bool,
    table: bool,
    as_dict: str | None,
) -> None:
    """List job records below this path."""
    if table and state:
        raise click.UsageError("'--table' and '--state' are mutually exclusive")

    path = obj.jobpath
    state_path: Path | None = None
    if state or state_only or table:
        state_path = obj.statepath + path

    if table:
        async with obj.conn.d.walk(obj.path + path).stream_in() as mon:
            async for r in mon:
                _, p, d, *_m = r
                try:
                    s = await obj.conn.d_get(obj.statepath + path + p)
                except KeyError:
                    st = "-never-"
                else:
                    if s.get("started", 0) > s.get("stopped", 0):
                        st = s.get("node", "?")
                    else:
                        st = "-stopped-"
                print(path + p, d.get("code"), st, file=obj.stdout)
        return

    await data_get(
        obj.conn,
        obj.path + path,
        as_dict=as_dict,
        item_mangle=partial(
            _state_fix,
            obj,
            state_path,
            state_only,
            None if as_dict else path,
        ),
        out=obj.stdout,
    )


@at_cli.command("state")
@click.option("-r", "--result", is_flag=True, help="Print only the actual result.")
@click.pass_obj
async def state_(obj: attrdict, result: bool) -> None:
    """Get the status of a job."""
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")
    if not len(obj.jobpath):
        raise click.UsageError("You need a non-empty path.")

    try:
        res = await obj.conn.d_get(obj.statepath + obj.jobpath)
    except KeyError:
        if obj.debug:
            print("Not found (yet?)", file=sys.stderr)
        sys.exit(1)
    if result:
        res = res.get("result") if isinstance(res, dict) else None
    else:
        add_dates(res)
    yprint(res, stream=obj.stdout)


@at_cli.command()
@click.option("-s", "--state", is_flag=True, help="Add state data.")
@click.pass_obj
async def get(obj: attrdict, state: bool) -> None:
    """Read a single job record."""
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")
    if not obj.jobpath:
        raise click.UsageError("You need a non-empty path.")

    try:
        res = await obj.conn.d_get(obj.path + obj.jobpath)
    except KeyError:
        print("Not found.", file=sys.stderr)
        return

    add_dates(res)
    if state:
        try:
            sres = await obj.conn.d_get(obj.statepath + obj.jobpath)
        except KeyError:
            pass
        else:
            add_dates(sres)
            res["state"] = sres
    yprint(res, stream=obj.stdout)


@at_cli.command()
@click.option("-f", "--force", is_flag=True, help="Force deletion even if messy.")
@click.pass_obj
async def delete(obj: attrdict, force: bool) -> None:
    """Remove a job record."""
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")
    if not obj.jobpath:
        raise click.UsageError("You need a non-empty path.")

    try:
        val = await obj.conn.d_get(obj.path + obj.jobpath)
    except KeyError:
        if obj.debug:
            print("Does not exist.", file=obj.stdout)
        return

    if "target" not in val:
        val["target"] = None
    if val["target"] is not None:
        val["target"] = None
        await obj.conn.d_set(obj.path + obj.jobpath, val)
        if not force:
            if obj.debug:
                print("'target' was set: cleared but not deleted.", file=obj.stdout)
            return

    try:
        sres = await obj.conn.d_get(obj.statepath + obj.jobpath)
    except KeyError:
        sres = None
    if not force and isinstance(sres, dict) and sres.get("stopped", 0) < sres.get("started", 0):
        if obj.debug:
            print("Still running, not deleted.", file=obj.stdout)
        return

    if sres is not None:
        await obj.conn.d.delete(obj.statepath + obj.jobpath)
    await obj.conn.d.delete(obj.path + obj.jobpath)
    if obj.debug:
        print("Deleted.", file=obj.stdout)


@at_cli.command("set")
@click.option("-c", "--code", help="Path to the code that should run.")
@click.option("-C", "--copy", help="Use this entry as a template.")
@click.option("-t", "--time", "tm", help="Time the code should next run at. '-': never.")
@click.option("-r", "--repeat", type=int, help="Seconds the code should re-run after.")
@click.option("-k", "--ok", type=float, help="Code is OK if it ran this many seconds.")
@click.option("-b", "--backoff", type=float, help="Back-off factor. Default: 1.4.")
@click.option(
    "-d",
    "--delay",
    type=int,
    help="Seconds the code should retry after (with back-off).",
)
@click.option("-i", "--info", help="Short human-readable information.")
@attr_args
@click.pass_obj
async def set_(
    obj: attrdict,
    code: str | None,
    tm: str | None,
    info: str | None,
    ok: float | None,
    repeat: int | None,
    delay: int | None,
    backoff: float | None,
    copy: str | None,
    **kw: Any,
) -> None:
    """Add or modify a job record.

    Code typically requires some input parameters. Use ``-v NAME VALUE``
    for string values, ``-p NAME VALUE`` for paths, and ``-e NAME VALUE``
    for evaluated data. ``-e NAME -`` deletes an item.
    """
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")

    code_p: Path | None = P(code) if code is not None else None
    copy_p: Path | None = P(copy) if copy is not None else None
    path = obj.path + obj.jobpath

    try:
        if copy_p is not None:
            res = await obj.conn.d_get(copy_p)
        else:
            res = await obj.conn.d_get(path)
    except KeyError:
        if copy_p is not None:
            raise click.UsageError("--copy: use the complete path to an existing entry") from None
        if code_p is None:
            raise click.UsageError("New entry, need code") from None
        res = {}

    if copy_p is not None and "code" not in res:
        raise click.UsageError("'--copy' needs a runner entry")

    vl: attrdict = attrdict(**res.setdefault("data", {}))
    vl = process_args(vl, **kw)
    res["data"] = vl

    if code_p is not None:
        res["code"] = code_p
    if ok is not None:
        res["ok_after"] = ok
    if info is not None:
        res["info"] = info
    if backoff is not None:
        res["backoff"] = backoff
    if delay is not None:
        res["delay"] = delay
    if repeat is not None:
        res["repeat"] = repeat
    if tm is not None:
        if tm == "-":
            res["target"] = None
        else:
            res["target"] = time.time() + float(tm)

    await obj.conn.d_set(path, res)


@at_cli.command("debug")
@click.option(
    "-b",
    "--break",
    "use_break",
    is_flag=True,
    help="Drop into pdb before calling the snippet.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Take over the job even if another runner currently owns it.",
)
@attr_args
@click.pass_obj
async def debug_(
    obj: attrdict,
    use_break: bool,
    force: bool,
    **kw: Any,
) -> None:
    """Run a single job interactively, for debugging.

    No actor coordination, no scheduling.  The job's stored ``data`` is
    taken as-is; ``-v``/``-p``/``-e`` overrides are merged on top for
    this run only.

    ``state.node`` is set to the client connection ID for the duration
    of the call.  If a different runner already owns the job, ``-f`` is
    required to steal it.

    Output emitted by the snippet through ``_log`` (at DEBUG level and
    up) is mirrored to stderr regardless of the global verbosity.
    """
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")
    if not obj.jobpath:
        raise click.UsageError("A job path is required.")

    overrides = process_args(attrdict(), **kw)
    job_path = obj.path + obj.jobpath
    state_path = obj.statepath + obj.jobpath

    try:
        res = await debug_run(
            obj.conn,
            job_path,
            state_path,
            data_overrides=overrides,
            use_pdb=use_break,
            force=force,
            log_stream=sys.stderr,
        )
    except RuntimeError as exc:
        raise click.UsageError(str(exc)) from None
    if res is not None:
        yprint(res, stream=obj.stdout)


@cli.command(short_help="Show runners' keepalive messages")
@click.pass_obj
async def monitor(obj: attrdict) -> None:
    """Watch the runners' periodic keepalive messages on the actor topic."""
    if obj.subpath[-1] == "-":
        raise click.UsageError("Group '-' can only be used for listing.")

    topic = P("run.job") | obj.job_cfg["name"]
    async with obj.conn.monitor(topic, subtree=True) as mon:
        async for msg in mon:
            yprint({"topic": msg.topic, "data": msg.data}, stream=obj.stdout)
            print("---", file=obj.stdout)
