"""
Basic support for SEW motors.

This module sets up the ``moat dev sew`` command subgroup.
"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position

import asyncclick as click

from moat.util import combine_dict, merge
from moat.lib.config import CFG
from moat.lib.path import P, Path
from moat.lib.run import load_subgroup

from typing import Any

log = logging.getLogger()


@load_subgroup(prefix="moat.dev.sew")
@click.pass_obj
@click.option("--sub", "-s", type=P, default=P("dev.sew"), help="SEW sub-config")
async def cli(obj: Any, sub: Path) -> None:
    """Device Manager for SEW MOVITRAC motor controllers."""
    from moat.mqtt.client import get_codec  # noqa: PLC0415

    obj.sub = sub
    obj.sew = combine_dict(obj.cfg._get(sub), obj.cfg["dev"]["sew"])  # noqa:SLF001
    CFG.with_("moat.mqtt")
    merge(
        obj.sew.setdefault("mqtt", {}),
        obj.cfg.get("mqtt", {}).get("client", {}),
        CFG.moat.mqtt.client,
        replace=False,
    )

    mqw: dict[str, Any] = obj.sew["mqtt"].get("will", {})
    # the defaults have no will (topic and message are None)
    if isinstance(top := mqw.get("topic"), Path):
        mqw["topic"] = "/".join(top)
    if (msg := mqw.get("message")) is not None:
        codec = get_codec(obj.sew["mqtt"]["codec"])
        mqw["message"] = codec.encode(msg)


@cli.command("run")
@click.pass_obj
async def run_(obj: Any) -> None:
    """
    Run a simple SEW MOVITRAC control process.
    """
    cfg: dict[str, Any] = obj.sew

    from .control import run  # noqa: PLC0415

    await run(cfg, name="moat." + str(obj.sub))


@cli.command("set")
@click.pass_obj
@click.argument("value", type=float)
async def set_(obj: Any, value: float) -> None:
    """Set the SEW MOVITRAC to a given power level (-1…1)."""
    cfg: dict[str, Any] = obj.sew
    if value < -1 or value > 1:
        log.error("Value must be between -1 and 1")
        return

    from .control import set_val  # noqa: PLC0415

    await set_val(cfg, value)
