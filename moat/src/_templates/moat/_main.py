"""
MoaT sub-tool template
"""

from __future__ import annotations

from moat.lib.run import load_subgroup


@load_subgroup(prefix="moat.new.component")
async def cli() -> None:
    """Something new."""
    pass


@cli.command(name="test")
async def test_() -> None:
    """
    Testing things.
    """
    pass
