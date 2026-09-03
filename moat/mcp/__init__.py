"""
A generic MCP (Model Context Protocol) server for MoaT.

This package provides an MCP server that runs over stdio and exposes one or
more *services*. Each service lives in a submodule ``moat.mcp.<name>`` and
contributes a set of MCP tools, typically backed by a connection to some
MoaT subsystem.

The set of enabled services and their configuration is taken from the
``moat.mcp.services`` configuration mapping.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

from moat.util import CtxObj, NotGiven
from moat.lib.run import load_ext

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskGroup

    from moat.util import attrdict

    from collections.abc import AsyncIterator

__all__ = ["Service", "load_service", "services"]


class Service(CtxObj):
    """
    Base class for an MCP service.

    A service connects to some MoaT subsystem and registers MCP tools that
    operate on it. Subclasses are instantiated with the service
    configuration and a task group for background work, then entered as an
    async context manager (see :class:`~moat.util.CtxObj`). While the
    context is active they register their tools on the shared
    :class:`~mcp.server.fastmcp.FastMCP` server.

    The service ``name`` is used as a prefix for the tool names, so a
    ``get_value`` tool of the ``link`` service is announced as
    ``link_get_value``.
    """

    #: The service name. Subclasses must set this.
    name: str

    def __init__(self, cfg: attrdict, tg: TaskGroup):
        self.cfg = cfg
        self.tg = tg

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Service]:
        """
        Set up the service's connection.

        Subclasses override this to acquire whatever resources they need
        (e.g. a server connection). The default does nothing.
        """
        yield self

    async def register(self, mcp: Any) -> None:
        """
        Register this service's MCP tools on ``mcp``.

        ``mcp`` is a :class:`mcp.server.fastmcp.FastMCP` server. Subclasses
        must implement this. Tool names should be prefixed with :attr:`name`
        to avoid clashes between services.
        """
        raise NotImplementedError

    def tool_name(self, name: str) -> str:
        """Return ``name`` prefixed with the service name."""
        return f"{self.name}_{name}"


def load_service(name: str) -> type[Service]:
    """
    Load the :class:`Service` subclass for ``name``.

    The class is looked up as ``Service`` in the module
    ``moat.mcp.<name>``.

    Raises:
        ValueError: no such service exists.
    """
    cls = load_ext("moat.mcp", name, "Service")
    if cls is None:
        raise ValueError(f"No MCP service named {name!r}")
    return cls


@asynccontextmanager
async def services(cfg: attrdict, tg: TaskGroup) -> AsyncIterator[list[Service]]:
    """
    Instantiate and enter all configured services.

    Args:
        cfg: the ``moat.mcp`` configuration subtree.
        tg: a task group for the services' background work.

    Yields:
        The list of active :class:`Service` instances.
    """
    svc: list[Service] = []
    async with AsyncExitStack() as stack:
        for sname, scfg in cfg.get("services", {}).items():
            if not isinstance(scfg, Mapping):
                if scfg in (None, False, NotGiven):
                    continue
                raise ValueError(f"MCP config for {sname!r} is {scfg!r} ??")
            cls = load_service(sname)
            service = cls(scfg, tg)
            await stack.enter_async_context(service)
            svc.append(service)
        yield svc
