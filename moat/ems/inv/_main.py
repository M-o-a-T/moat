"""
Main code for inverter control
"""

from __future__ import annotations

import sys

import asyncclick as click

try:
    from moat.util import yload
except ImportError:
    import ruyaml

    yaml = ruyaml.YAML()
    yload = yaml.load

import logging

from asyncdbus.message_bus import BusType, MessageBus

from moat.ems.inv import InvControl

logger = logging.getLogger(__name__)

_modes = """
Modes:

"""
for _i, _c in InvControl.MODES.items():
    # pylint:disable=protected-access
    _modes += "\b\n"
    _modes += f"{_c._name:<15s} {_c.__doc__}\n\n\b\n"  # noqa:SLF001
    _modes += (
        "   "
        + _c._doc["_l"].replace("\n", "\n   ").replace("\n   \n", "\n\n\b\n").rstrip(" ")  # noqa:SLF001
        + "\n\b\n"
    )
    if len(_c._doc) > 1:  # noqa:SLF001
        _modes += "   Operational Variables:\n"
    for _k, _v in _c._doc.items():  # noqa:SLF001
        if _k[0] == "_":
            continue
        _modes += f"   {_k:<15s} {_v.strip()}\n"

    _modes += "\n"


@click.command(epilog=_modes)
@click.option("--debug", "-d", is_flag=True)
@click.option("--no-op", "-n", is_flag=True)
@click.option("--mode", "-m", help="Inverter mode")
@click.option(
    "--param",
    "-p",
    "param",
    nargs=2,
    type=(str, str),
    multiple=True,
    help="Parameter (evaluated)",
)
@click.option(
    "--config",
    "--cfg",
    "-c",
    "config",
    type=click.File("r"),
    help="Configuration file (YAML)",
)
async def cli(debug, mode, no_op, param, config):
    """
    This program controls a Victron Energy inverter.
    """
    # Init logging
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    logger.debug("%s is starting up", __file__)

    sys.path.insert(0, "/data/moat")
    sys.path.insert(1, "/data/moat/bus/python")

    if config:
        cfg = yload(config)
        config.close()
    else:
        cfg = {}
    op = cfg.setdefault("op", {})
    op.setdefault("debug", 1)
    op["debug"] += debug
    op["fake"] = no_op

    for k, v in param:
        op[k] = float(v)

    async with MessageBus(bus_type=BusType.SYSTEM).connect() as bus, InvControl(bus, cfg) as inv:
        await inv.run(mode)


if __name__ == "__main__":
    # pylint:disable=no-value-for-parameter
    cli(_anyio_backend="trio")
