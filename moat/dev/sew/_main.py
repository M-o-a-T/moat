"""
Basic support for SEW motors
"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position

import asyncclick as click

from moat.util import load_subgroup, P, Path, combine_dict, merge, load_cfg

log = logging.getLogger()


@load_subgroup(prefix="moat.dev.sew")
@click.pass_obj
@click.option("--sub", "-s", type=P, default=P("dev.sew"), help="SEW sub-config")
async def cli(obj, sub):
    """Device Manager for SEW MOVITRAC motor controllers"""
    from moat.mqtt.client import get_codec

    obj.sub = sub
    obj.sew = combine_dict(obj.cfg._get(sub), obj.cfg["dev"]["sew"])
    merge(
        obj.sew.setdefault("mqtt", {}),
        obj.cfg.get("mqtt", {}).get("client", {}),
        load_cfg("moat.mqtt")["mqtt"]["client"],
        replace=False,
    )

    mqw = obj.sew["mqtt"].get("will", {})
    try:
        top = mqw["topic"]
    except KeyError:
        pass
    else:
        if isinstance(top, Path):
            mqw["topic"] = "/".join(top)
    try:
        msg = mqw["message"]
    except KeyError:
        pass
    else:
        codec = get_codec(obj.sew["mqtt"]["codec"])
        mqw["message"] = codec.encode(msg)


@cli.command("run")
@click.pass_obj
async def run_(obj):
    """
    Run a simple SEW MOVITRAC control process
    """
    cfg = obj.sew

    from .control import run

    await run(cfg, name="moat." + str(obj.sub))


@cli.command("set")
@click.pass_obj
@click.argument("value", type=float)
async def set_(obj, value):
    cfg = obj.sew
    if value < -1 or value > 1:
        log.error("Value must be between -1 and 1")
        return

    from .control import set

    await set(cfg, value)
