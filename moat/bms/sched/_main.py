#!/usr/bin/env python3
"""
Basic tool support

"""
import logging  # pylint: disable=wrong-import-position

import asyncclick as click

log = logging.getLogger()


@click.group()
async def cli():
    """Battery Manager: Scheduling"""
    pass  # pylint: disable=unnecessary-pass


@cli.command()
def analyze():
    """TODO"""
    print("YES")
