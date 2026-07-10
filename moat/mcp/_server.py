"""
FastMCP server runner for MoaT.

This module depends on the external ``mcp`` package and is therefore kept
separate from the type-checked service logic in :mod:`moat.mcp`.
"""

import anyio

from mcp.server.fastmcp import FastMCP

from . import services

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict

__all__ = ["run"]


async def run(cfg: "attrdict", name: str = "moat") -> None:
    """
    Run the MCP server over stdio.

    Instantiates every service configured in ``cfg.services``, registers
    their tools, and serves MCP requests on stdin/stdout until cancelled.

    Args:
        cfg: the ``moat.mcp`` configuration subtree.
        name: the server name announced to MCP clients.
    """
    async with anyio.create_task_group() as tg, services(cfg, tg) as svc:
        mcp = FastMCP(name)
        for service in svc:
            await service.register(mcp)
        try:
            await mcp.run_stdio_async()
        finally:
            tg.cancel_scope.cancel()
