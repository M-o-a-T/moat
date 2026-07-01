"""
Command line interface for the MoaT MCP server.
"""

from __future__ import annotations

import asyncclick as click

from moat.lib.run import load_subgroup


@load_subgroup(prefix="moat.mcp")
@click.pass_obj
async def cli(obj):
    """
    MCP (Model Context Protocol) server for MoaT.

    Exposes MoaT subsystems to MCP clients. The set of enabled services is
    configured under ``moat.mcp.services``.
    """
    obj  # noqa: B018


@cli.command()
@click.option("-n", "--name", default="moat", help="Server name announced to MCP clients.")
@click.pass_obj
async def stdio(obj, name):
    """
    Serve MCP requests over stdin/stdout.

    This connects every configured service and exposes its tools to an MCP
    client on stdin/stdout.
    """
    from moat.mcp._server import run  # noqa: PLC0415

    await run(obj.cfg.mcp, name=name)
