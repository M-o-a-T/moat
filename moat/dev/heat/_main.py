"""
Basic heater tool support.

This module sets up the ``moat dev heat`` command subgroup.
"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position

import asyncclick as click

from moat.lib.run import load_subgroup

from typing import Any

log = logging.getLogger()


@load_subgroup(prefix="moat.dev.heat")
@click.pass_obj
async def cli(obj: Any) -> None:
    """Device Manager for heaters."""
    obj  # noqa:B018  pylint: disable=pointless-statement  # TODO
