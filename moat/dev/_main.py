#!/usr/bin/env python3
"""
Basic tool support

"""
import logging  # pylint: disable=wrong-import-position

import asyncclick as click
from moat.util import load_subgroup

log = logging.getLogger()


@load_subgroup(prefix="moat.dev")
@click.pass_obj
async def cli(obj):
    """Device Manager"""
    obj  # pylint: disable=pointless-statement  # TODO
