from __future__ import annotations

"""
Basic heater tool support

"""

import asyncclick as click

from moat.util import load_subgroup

import logging  # pylint: disable=wrong-import-position

log = logging.getLogger()


@load_subgroup(prefix="moat.dev.heat")
@click.pass_obj
async def cli(obj):
    """Device Manager for heaters"""
    obj  # noqa:B018  pylint: disable=pointless-statement  # TODO
