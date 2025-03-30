"""
MoaT sub-tool template
"""

from __future__ import annotations

import asyncclick as click

from moat.util import load_subgroup


@load_subgroup(prefix="moat.new.component")
async def cli():
    """Something new."""
    pass


@cli.command(name="test")
async def test_():
    """
    Testing things.
    """
    pass
