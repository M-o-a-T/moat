#!/usr/bin/env python3
"""
Basic tool support

"""
from getopt import getopt

import asyncclick as click
from moat.util import load_subgroup

import logging  # pylint: disable=wrong-import-position

log = logging.getLogger()

@load_subgroup(sub_pre="moat.bms")
@click.pass_obj
async def cli(obj):
    """Battery Manager"""
    pass  # pylint: disable=unnecessary-pass

