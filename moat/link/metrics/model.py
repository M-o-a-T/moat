"""
Node model for metrics series configuration.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each server entry contains per-series child nodes.
"""

from __future__ import annotations

import logging

from attrs import define, field

from moat.util import NotGiven
from moat.link.node import Node

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio

    from moat.lib.rpc import Key

    from typing import Any

logger = logging.getLogger(__name__)


@define
class MetricPoint:
    """
    A backend-agnostic metric data point.

    Args:
        series: Series name.
        value: Numeric value.
        tags: Dictionary of tags.
        mode: Backend-specific mode string.
    """

    series: str
    value: float
    tags: dict[str, Any]
    mode: str


def _test_hook(e: MetricPoint) -> None:
    """Hook for testing; called with every MetricPoint before sending."""


@define
class MetricsEntry(Node):
    """A single metrics series mapping.

    Reads a source value from MoaT-Link, applies *factor* and *offset*,
    and writes the result to a metrics backend.
    """

    _work: anyio.CancelScope | None = field(init=False, default=None)
    _t_last: float | None = field(init=False, default=None)

    # --- helpers --------------------------------------------------------

    @property
    def source(self) -> tuple | None:
        """Source path from the stored config, or None."""
        d = self.data_
        if d is NotGiven or not isinstance(d, dict):
            return None
        return d.get("source")

    @property
    def series(self) -> str | None:
        """Akumuli series name."""
        d = self.data_
        if d is NotGiven or not isinstance(d, dict):
            return None
        return d.get("series")

    @property
    def tags(self) -> dict | None:
        """Akumuli tags dict."""
        d = self.data_
        if d is NotGiven or not isinstance(d, dict):
            return None
        return d.get("tags")

    @property
    def mode(self) -> str:
        """Backend-specific data-series mode."""
        d = self.data_ if self.data_ is not NotGiven else {}
        m = d.get("mode", "gauge") if isinstance(d, dict) else "gauge"
        return m if isinstance(m, str) else str(m)

    @property
    def attr(self) -> tuple:
        """Attribute path to extract from the watched value."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return d.get("attr", ()) if isinstance(d, dict) else ()

    @property
    def factor(self) -> float:
        """Multiplicative scaling factor."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return d.get("factor", 1) if isinstance(d, dict) else 1

    @property
    def offset(self) -> float:
        """Additive offset."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return d.get("offset", 0) if isinstance(d, dict) else 0

    @property
    def t_min(self) -> float | None:
        """Minimum interval between writes, in seconds."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return d.get("t_min") if isinstance(d, dict) else None

    def is_complete(self) -> bool:
        """Check whether this entry has enough data to start a worker."""
        return bool(self.source and self.series and self.tags)


@define
class MetricsServer(Node):
    """Represents one metrics server instance in the configuration tree.

    Children are :class:`MetricsEntry` nodes.
    """

    def add_child(self, item: Key) -> MetricsEntry:
        """Create child entries as :class:`MetricsEntry`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = MetricsEntry()
        return s


@define
class MetricsRoot(Node):
    """Root of the metrics configuration tree.

    Children are :class:`MetricsServer` nodes.
    """

    def add_child(self, item: Key) -> MetricsServer:
        """Create child servers as :class:`MetricsServer`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = MetricsServer()
        return s
