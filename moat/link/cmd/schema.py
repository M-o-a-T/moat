# command line interface  # noqa: D100
from __future__ import annotations

import anyio
import time
from contextlib import suppress

import asyncclick as click

from moat.util import yprint
from moat.lib.path import P, Path
from moat.link.client import Link
from moat.link.schema import schema_path, validate_instance

from typing import Any


@click.group(short_help="Manage schemas.")  # pylint: disable=undefined-variable
@click.pass_context
async def cli(ctx):
    """
    This subcommand reads schema entries stored in the MoaT-Link service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, common=True))


@cli.command()
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def get(obj, path):
    """
    Retrieve the schema for a path.
    """
    res = await obj.conn.d_search(schema_path(path))
    yprint(res, stream=obj.stdout)


async def _schema_error(conn, path: Path, data: Any) -> Exception | None:
    """Return the schema validation error for one message, if any."""
    try:
        schema = await conn.d_search(schema_path(path))
    except KeyError:
        return None
    try:
        validate_instance(schema, data)
    except Exception as exc:
        return exc
    return None


async def _schema_record_error(conn, path: Path, data: Any, exc: Exception) -> None:
    """Write one schema error record."""
    await conn.e_info(
        P("schema") + path,
        "Schema mismatch",
        data_path=path,
        data=data,
        detail=str(exc),
    )


@cli.command()
@click.option(
    "-l",
    "--limit",
    type=float,
    default=60.0,
    show_default=True,
    help="Minimum number of seconds between created error records. 0 disables limiting.",
)
@click.option("-v", "--verbose", is_flag=True, help="Print running mismatch counters.")
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def monitor(obj, path, limit, verbose):
    """
    Monitor a subtree and report schema mismatches as errors.
    """
    n_bad = 0
    n_err = 0
    next_err = 0.0
    qw, qr = anyio.create_memory_object_stream(10)

    async def _reader():
        try:
            async with obj.conn.d_watch(path, state=None, subtree=True) as mon:
                async for rel, data in mon:
                    with suppress(anyio.WouldBlock):
                        qw.send_nowait((rel, data))
        finally:
            await qw.aclose()

    async def _worker():
        nonlocal n_bad, n_err, next_err
        async for rel, data in qr:
            full = path + rel
            exc = await _schema_error(obj.conn, full, data)
            if exc is None:
                continue
            n_bad += 1
            now = time.monotonic()
            if limit <= 0 or now >= next_err:
                await _schema_record_error(obj.conn, full, data, exc)
                n_err += 1
                next_err = now + limit
            if verbose:
                click.echo(f"invalid: {n_bad}  recorded: {n_err}", err=True)

    async with anyio.create_task_group() as tg:
        tg.start_soon(_reader)
        tg.start_soon(_worker)


@cli.command()
@click.option("-v", "--verbose", is_flag=True, help="Show a mismatch summary.")
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def check(obj, path, verbose):
    """
    Check all stored messages in a subtree against schemas.
    """
    n_bad = 0

    async with obj.conn.d_watch(path, state=True, subtree=True) as mon:
        async for rel, data in mon:
            full = path + rel
            exc = await _schema_error(obj.conn, full, data)
            if exc is None:
                continue
            n_bad += 1
            yprint(dict(path=full, detail=str(exc)), stream=obj.stdout)
            print("---", file=obj.stdout)
            obj.stdout.flush()

    if verbose:
        click.echo(f"invalid: {n_bad}", err=True)
