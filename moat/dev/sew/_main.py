"""
Basic support for SEW motors
"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position
import anyio

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
    merge(obj.sew.setdefault("mqtt", {}), obj.cfg.get("mqtt",{}).get("client",{}), load_cfg("moat.mqtt")["mqtt"]["client"], replace=False)

    mqw = obj.sew["mqtt"].get("will",{})
    try:
        top = mqw["topic"]
    except KeyError:
        pass
    else:
        if isinstance(top,Path):
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
    cfg = obj.sew

    from moat.util import yprint
    from moat.mqtt.client import open_mqttclient, CodecError

    yprint(cfg)
    from .control import run

    await run(cfg, name=str(obj.sub))
