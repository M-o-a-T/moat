# command line interface
from __future__ import annotations

import anyio
import asyncclick as click
from collections.abc import Mapping

from moat.util import yprint, attrdict, as_service, P, attr_args
from moat.kv.data import res_get, res_update, node_attr

import logging

logger = logging.getLogger(__name__)


@click.group(short_help="Manage GPIO controllers.")
async def cli():
    """
    List GPIO controllers, modify device handling …
    """
    pass


@cli.command()
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def dump(obj, path):
    """Emit the current state as a YAML file."""
    cfg = obj.cfg.kv.gpio
    res = {}
    if len(path) > 3:
        raise click.UsageError("Only up to three path elements (host.controller:pin) allowed")

    async for r in obj.client.get_tree(
        cfg.prefix + path,
        nchain=obj.meta,
        max_depth=4 - len(path),
    ):
        # pl = len(path) + len(r.path)
        rr = res
        if r.path:
            for rp in r.path:
                rr = rr.setdefault(rp, {})
        rr["_"] = r if obj.meta else r.value
    yprint(res, stream=obj.stdout)


@cli.command("list")
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def list_(obj, path):
    """List the next stage."""
    cfg = obj.cfg.kv.gpio
    res = {}
    if len(path) > 3:
        raise click.UsageError("Only up to three path elements (host.controller:pin) allowed")

    for r in await obj.client.list(cfg.prefix + path, empty=True):
        print(r, file=obj.stdout)


@cli.command("attr")
@attr_args
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def attr_(obj, path, **kw):
    """Set/get/delete attributes of a given GPIO element.

    `--eval` without a value deletes the attribute.
    """
    cfg = obj.cfg.kv.gpio
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.controller:pin) required")
    await node_attr(obj, cfg.prefix + path, **kw)


@cli.command()
@click.argument("path", nargs=1, type=P)
@click.pass_obj
async def delete(obj, path):
    """
    Delete a port.
    """
    cfg = obj.cfg.kv.gpio
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.controller:pin) required")
    res = await obj.client.delete(cfg.prefix + path)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
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
    cfg = obj.cfg.kv.gpio
    if len(path) != 3:
        raise click.UsageError("Three path elements (host.controller:pin) required")
    res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 1)
    val = res.get("value", attrdict())

    if type is None:
        raise click.UsageError("Port type is mandatory.")
    if mode is None:
        raise click.UsageError("Port mode is mandatory.")
    attr = (("type", typ), ("mode", mode)) + attr
    for k, v in attr:
        if k == "count":
            if v == "+":
                v = True
            elif v == "-":
                v = False
            elif v in "xX*":
                v = None
            else:
                raise click.UsageError("'%s' wants one of + - X" % (k,))
        elif k in ("low", "skip", "flow"):
            if v == "+":
                v = True
            elif v == "-":
                v = False
            else:
                raise click.UsageError("'%s' wants one of + -" % (k,))
        elif k in {"src", "dest"}:
            v = P(v)
        else:
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
        val[k] = v

    await _attr(obj, (), val, path, False, res)


async def _attr(obj, attr, value, path, eval_, res=None):
    # Sub-attr setter. (Or whole-attr-setter if 'attr' is empty.)
    # Special: if eval_ is True, a value of '-' deletes. A mapping replaces instead of updating.
    cfg = obj.cfg.kv.gpio
    if res is None:
        res = await obj.client.get(cfg.prefix + path, nchain=obj.meta or 2)
    try:
        val = res.value
    except AttributeError:
        res.chain = None
    if eval_:
        if value is None:
            pass  # value = res_delete(res, attr)
        else:
            value = eval(value)  # pylint: disable=eval-used
            if isinstance(value, Mapping):
                # replace
                # value = res_delete(res, attr)
                value = value._update(attr, value=value)
            else:
                value = res_update(res, attr, value=value)
    else:
        if value is None:
            if not attr and obj.meta:
                val = res
            else:
                val = res_get(res, attr)
            yprint(val, stream=obj.stdout)
            return
        value = res_update(res, attr, value=value)
    res = await obj.client.set(cfg.prefix + path, value=value, nchain=obj.meta, chain=res.chain)
    if obj.meta:
        yprint(res, stream=obj.stdout)


@cli.command()
@click.argument("name", nargs=1)
@click.argument("controller", nargs=-1)
@click.pass_obj
async def monitor(obj, name, controller):
    """Stand-alone task to monitor a single contoller.

    The first argument must be the local host name.
    """
    from .task import task
    from .model import GPIOroot

    server = await GPIOroot.as_handler(obj.client)
    await server.wait_loaded()
    sub = server[name]
    if controller:
        sub = (sub[x] for x in controller)
    async with as_service(obj) as s:
        async with anyio.create_task_group() as tg:
            e = []
            for chip in sub:
                evt = anyio.Event()
                tg.start_soon(task, chip, evt)
                e.append(evt)
            for evt in e:
                await evt.wait()
            s.set()
