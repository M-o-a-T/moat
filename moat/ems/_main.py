#!/usr/bin/env python3
"""
Basic tool support

"""

from __future__ import annotations

import logging  # pylint: disable=wrong-import-position

import asyncclick as click
from moat.util import load_subgroup

log = logging.getLogger()


@load_subgroup(sub_pre="moat.ems")
@click.pass_obj
async def cli(obj):
    """Energy Management System"""
    obj  # pylint: disable=pointless-statement  # TODO
