"""
Akumuli backend for metrics.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncakumuli as akumuli

from .._base import Backend as _Backend  # noqa:TID252

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.link.metrics.model import MetricPoint

    from collections.abc import AsyncIterator
    from typing import Self

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
        cfg = self.cfg.get("server", {})
        if "delta" in self.cfg:
            cfg = dict(cfg)
            cfg["delta"] = self.cfg["delta"]
        async with akumuli.connect(**cfg) as self.srv:
            try:
                yield self
            finally:
                self.srv = None  # noqa:PLW2901

    async def put(self, point: MetricPoint) -> None:
        """
        Send a metric point to Akumuli.

        Args:
            point: The data point to send.
        """
        from asyncakumuli import DS  # noqa: PLC0415

        mode = getattr(DS, point.mode) if isinstance(point.mode, str) else point.mode
        entry = akumuli.Entry(
            series=point.series,
            value=cast("int", point.value),
            tags=point.tags,
            time=point.timestamp,
            mode=mode,
        )
        await self.srv.put(entry)
