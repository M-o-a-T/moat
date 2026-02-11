"""
Akumuli backend for metrics.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncakumuli as akumuli

from . import Backend as _Backend

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any, Self

__all__ = ["Backend"]


class Backend(_Backend):
    """The Akumuli backend driver."""

    def __init__(self, cfg: dict, name: str):
        """
        Initialize Akumuli backend.

        Args:
            cfg: Configuration dict with host, port, delta, etc.
            name: Name of the backend instance.
        """
        super().__init__(cfg, name)
        self.srv = None

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Self]:
        """Connect to the Akumuli server."""
        conn_cfg = {
            "host": self.cfg.get("host", "localhost"),
            "port": self.cfg.get("port", 8282),
            "delta": self.cfg.get("delta", True),
        }
        async with akumuli.connect(**conn_cfg) as self.srv:
            try:
                yield self
            finally:
                self.srv = None  # noqa:PLW2901

    async def put(self, entry: Any) -> None:
        """
        Send an entry to Akumuli.

        Args:
            entry: An asyncakumuli.Entry object.
        """
        await self.srv.put(entry)
