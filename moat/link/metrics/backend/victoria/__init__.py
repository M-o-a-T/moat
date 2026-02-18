"""
VictoriaMetrics backend for metrics.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncvictoria as victoria

from .._base import Backend as _Backend  # noqa:TID252

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.metrics.model import MetricPoint

    from collections.abc import AsyncIterator
    from typing import Self

__all__ = ["Backend"]


class Backend(_Backend):
    """The VictoriaMetrics backend driver."""

    def __init__(self, cfg: dict, name: str):
        """
        Initialize VictoriaMetrics backend.

        Args:
            cfg: Configuration dict with host, port, etc.
            name: Name of the backend instance.
        """
        super().__init__(cfg, name)
        self.srv = None

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Self]:
        """Connect to the VictoriaMetrics server."""
        conn_cfg = {
            "host": self.cfg.get("host", "localhost"),
            "port": self.cfg.get("port", 8282),
        }
        async with victoria.connect(**conn_cfg) as self.srv:
            try:
                yield self
            finally:
                self.srv = None  # noqa:PLW2901

    async def put(self, point: MetricPoint) -> None:
        """
        Send a metric point to VictoriaMetrics.

        Args:
            point: The data point to send.
        """
        from asyncvictoria import DS  # noqa: PLC0415

        mode = getattr(DS, point.mode) if isinstance(point.mode, str) else point.mode
        entry = victoria.Entry(
            series=point.series,
            value=point.value,
            tags=point.tags,
            time=point.timestamp,
            mode=mode,
        )
        await self.srv.put(entry)
