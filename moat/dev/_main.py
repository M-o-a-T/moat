"""
Basic tool support.

This module sets up the ``moat dev`` command subgroup.
"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position

import asyncclick as click

from moat.lib.run import load_subgroup

from typing import Any

log = logging.getLogger()


@load_subgroup(prefix="moat.dev")
@click.pass_obj
async def cli(obj: Any) -> None:
    """Device Manager."""
    obj  # noqa:B018
