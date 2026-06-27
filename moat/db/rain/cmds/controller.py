"""Command-line interface for irrigation controllers."""

from __future__ import annotations

import asyncclick as click

from moat.lib.run import AliasedGroup


@click.group(cls=AliasedGroup, short_help="Manage irrigation controllers")
@click.option("--name", "-n", type=str, default=None, help="Controller name")
@click.pass_obj
async def cli(obj, name):
    """Manage irrigation controllers."""
    obj.name = name
