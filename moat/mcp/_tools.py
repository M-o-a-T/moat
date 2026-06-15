"""
FastMCP tool registration for the MoaT-Link service.

This module depends on the external ``mcp`` package and deliberately avoids
``from __future__ import annotations``: FastMCP evaluates the tool signatures
at registration time and cannot resolve stringized annotations.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from .link import LinkService

__all__ = ["register_link"]


def register_link(mcp: "FastMCP", service: "LinkService") -> None:
    """
    Register the MoaT-Link tools of ``service`` on ``mcp``.

    Tool names are prefixed with the service name (``link``).

    Args:
        mcp: the FastMCP server to register on.
        service: the link service providing the backend.
    """
    backend = service.backend
    p = service.tool_name

    @mcp.tool(name=p("get_value"), description="Read the value stored at a dotted MoaT-Link path.")
    async def get_value(path: str) -> Any:
        return await backend.value_get(path)

    @mcp.tool(name=p("set_value"), description="Store a value at a dotted MoaT-Link path.")
    async def set_value(path: str, value: Any) -> str:
        await backend.value_set(path, value)
        return "ok"

    @mcp.tool(
        name=p("watch_start"),
        description=(
            "Start watching a dotted MoaT-Link path for changes. "
            "Returns a numeric watch ID used to poll and stop the watch. "
            "Set 'subtree' to also report changes below the path."
        ),
    )
    async def watch_start(path: str, subtree: bool = False) -> int:
        return await backend.watch_start(path, subtree)

    @mcp.tool(
        name=p("watch_get"),
        description=(
            "Retrieve pending changes for a watch. When given, wait up to "
            "'timeout' seconds for the first change; returns an empty list "
            "if none arrive. 'max_items' limits the number returned (0 = no "
            "limit)."
        ),
    )
    async def watch_get(
        watch_id: int, max_items: int = 0, timeout: "float | None" = None
    ) -> "list[dict[str, Any]]":
        return await backend.watch_get(watch_id, max_items, timeout)

    @mcp.tool(name=p("watch_stop"), description="Stop a watch and release its resources.")
    async def watch_stop(watch_id: int) -> str:
        await backend.watch_stop(watch_id)
        return "ok"
