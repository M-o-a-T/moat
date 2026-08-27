"""
Command-line interface for moat.link.gpio.

Manages GPIO line configurations stored in the MoaT-Link data tree
under the configured ``link.gpio.prefix``.  Each host contains chips;
each chip contains integer-numbered lines.
"""

from __future__ import annotations

import contextlib
import logging

import asyncclick as click

from moat.util import attrdict, yprint
from moat.lib.path import P
from moat.lib.run import AliasedGroup, attr_args
from moat.link._data import data_get, node_attr
from moat.link.announce import as_service
from moat.link.client import Link

logger = logging.getLogger(__name__)


@click.group(cls=AliasedGroup, short_help="Manage GPIO controllers.")
@click.pass_context
async def cli(ctx):
    """
    Manage GPIO controllers and line configurations.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(
        Link(cfg, common=True, only=getattr(obj, "link_name", None))
    )
    obj.gpio_cfg = obj.cfg.link.gpio
    obj.gpio_prefix = obj.gpio_cfg.prefix


@cli.command("dump")
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file."""
    if len(path) > 3:
        raise click.UsageError("Only up to three path elements (host.chip:pin) allowed")

    await data_get(obj.conn, obj.gpio_prefix + path, recursive=True, out=obj.stdout)


@cli.command("list")
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def list_(obj, path):
    """List the next stage."""
    if len(path) > 3:
        raise click.UsageError("Only up to three path elements (host.chip:pin) allowed")

    async with obj.conn.d_walk(obj.gpio_prefix + path, min_depth=1, max_depth=1) as mon:
        async for p, _d in mon:
            print(p[-1], file=obj.stdout)


@cli.command("attr")
@attr_args
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def attr_(obj, path, **kw):
    """Set/get/delete attributes of a given GPIO element.

    `--eval` without a value deletes the attribute.
    """
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.chip:pin) required")
    res, _meta = await node_attr(obj, obj.gpio_prefix + path, **kw)
    if getattr(obj, "meta", False):
        yprint(res, stream=obj.stdout)


@cli.command("delete")
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def delete(obj, path):
    """Delete a port."""
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.chip:pin) required")
    res = await obj.conn.d.delete(obj.gpio_prefix + path)
    if getattr(obj, "meta", False):
        yprint(res[0], stream=obj.stdout)


@cli.command("port")
@click.option("-t", "--type", "typ", help="Port type. 'input' or 'output'.")
@click.option("-m", "--mode", help="Port mode. Use '-' to disable.")
@click.option(
    "-a",
    "--attr",
    nargs=2,
    multiple=True,
    help="One attribute to set (NAME VALUE). May be used multiple times.",
)
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def port(obj, path, typ, mode, attr):
    """Add/modify a port. This is a shortcut for the "attr" command.

    \b
    Known attributes for types+modes:
      input:
        read: dest (path)
        count: read + interval (float), count (+-x for up/down/both)
        button: read + t_bounce (float), t_idle (float), skip (+- ignore noise?),
                       t_clear (float), flow (bool)
      output:
        write: src (path), state (path)
        oneshot: write + t_on (float), state (path)
        pulse:   oneshot + t_off (float)
      *:
        low: bool (signals are active-low if true)

    \b
    Paths elements are separated by spaces.
    "low" is the state of the wire when the input is False.
    Floats may be paths, in which case they're read from there when starting.
    """
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.chip:pin) required")
    try:
        res = await obj.conn.d_get(obj.gpio_prefix + path)
    except KeyError:
        res = {}
    val = res if isinstance(res, dict) else attrdict()

    if typ is None:
        raise click.UsageError("Port type is mandatory.")
    if mode is None:
        raise click.UsageError("Port mode is mandatory.")
    attr = (("type", typ), ("mode", mode)) + attr
    for k, v in attr:
        if k == "count":
            if v == "+":
                v = True  # noqa: PLW2901
            elif v == "-":
                v = False  # noqa: PLW2901
            elif v in "xX*":
                v = None  # noqa: PLW2901
            else:
                raise click.UsageError(f"'{k}' wants one of + - X")
        elif k in ("low", "skip", "flow"):
            if v == "+":
                v = True  # noqa: PLW2901
            elif v == "-":
                v = False  # noqa: PLW2901
            else:
                raise click.UsageError(f"'{k}' wants one of + -")
        elif k in {"src", "dest"}:
            v = P(v)  # noqa: PLW2901
        else:
            try:
                v = int(v)  # noqa: PLW2901
            except ValueError:
                with contextlib.suppress(ValueError):
                    v = float(v)  # noqa: PLW2901
        val[k] = v

    await obj.conn.d_set(obj.gpio_prefix + path, val)


@cli.command("monitor")
@click.argument("name", nargs=1)
@click.argument("chip", nargs=1)
@click.pass_obj
async def monitor(obj, name, chip):
    """Stand-alone task to monitor a single GPIO chip.

    The first argument is the host name, the second the chip name.
    """
    from .task import task  # noqa: PLC0415

    async with as_service(obj, host=False) as srv:
        await task(
            obj.conn,
            obj.gpio_cfg,
            name,
            chip,
            task_status=srv,
        )
