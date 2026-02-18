"""
Common code for metrics backends.

Currently the only backend supported is Akumuli, but who knows.
"""

from __future__ import annotations

import logging
from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager

from moat.util import CtxObj

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.metrics.model import MetricPoint

    from collections.abc import AsyncIterator
    from typing import Self

__all__ = ["Backend", "get_backend"]


class Backend(CtxObj, metaclass=ABCMeta):
    """Base class for metrics backends."""

    def __init__(self, cfg: dict, name: str):
        self.cfg = cfg
        self.name = name
        self.logger = logging.getLogger(f"moat.link.metrics.backend.{name}")

    @abstractmethod
    @asynccontextmanager
    async def connect(self, *a, **k) -> AsyncIterator[Self]:
        """
        This async context manager returns a connection to the backend.
        """

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        async with self.connect():
            yield self

    @abstractmethod
    async def put(self, point: MetricPoint) -> None:
        """
        Send a metric data point to the backend.

        Args:
            point: The data point to send.
        """


def get_backend(cfg: dict, name: str) -> Backend:
    """
    Fetch the backend named in the config and initialize it.
    """
    from importlib import import_module  # noqa: PLC0415

    backend_name = cfg.get("backend", "akumuli")
    if "." not in backend_name:
        backend_name = "moat.link.metrics.backend." + backend_name
    return import_module(backend_name).Backend(cfg, name)
