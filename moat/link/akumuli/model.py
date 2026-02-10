"""
Node model for Akumuli series configuration.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each server entry contains per-series child nodes.
"""

from __future__ import annotations

import logging

from asyncakumuli import DS, Entry
from attrs import define, field

from moat.util import NotGiven
from moat.link.node import Node

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anyio

    from moat.lib.rpc import Key

logger = logging.getLogger(__name__)


def _test_hook(e: Entry) -> None:
    """Hook for testing; called with every Entry before sending."""


@define
class AkumuliEntry(Node):
    """A single Akumuli series mapping.

    Reads a source value from MoaT-Link, applies *factor* and *offset*,
    and writes the result to an Akumuli series.
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
    def mode(self) -> DS:
        """Akumuli data-series mode."""
        d = self.data_ if self.data_ is not NotGiven else {}
        m = d.get("mode", "gauge") if isinstance(d, dict) else "gauge"
        return getattr(DS, m) if isinstance(m, str) else m

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
class AkumuliServer(Node):
    """Represents one Akumuli server instance in the configuration tree.

    Children are :class:`AkumuliEntry` nodes.
    """

    def add_child(self, item: Key) -> AkumuliEntry:
        """Create child entries as :class:`AkumuliEntry`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = AkumuliEntry()
        return s


@define
class AkumuliRoot(Node):
    """Root of the Akumuli configuration tree.

    Children are :class:`AkumuliServer` nodes.
    """

    def add_child(self, item: Key) -> AkumuliServer:
        """Create child servers as :class:`AkumuliServer`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = AkumuliServer()
        return s
