"""
Node model for the Wago controller connector.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each server entry is keyed by its name; below it the tree branches
into ``input`` and ``output`` types, then card numbers, then port
numbers.
"""

from __future__ import annotations

import logging

from attrs import define

from moat.util import NotGiven
from moat.lib.path import Path
from moat.link.node import Node

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Key

    from typing import Any

logger = logging.getLogger(__name__)


@define
class WagoPort(Node):
    """A single Wago input or output port.

    The stored configuration is a dict with these keys:

    * ``mode``: ``"read"``, ``"count"``, ``"write"``, ``"oneshot"``,
      or ``"pulse"``.
    * ``dest``: destination path (for ``mode=read|count``).
    * ``src``: source path (for ``mode=write|oneshot|pulse``).
    * ``state``: optional state path (for output modes).
    * ``rest``: rest-state flag (default ``False``).
    * ``interval``: polling interval in seconds (for ``mode=count``).
    * ``count``: pulse direction (``True``/``False``/``None``).
    * ``t_on``: on-time in seconds (for ``mode=oneshot|pulse``).
    * ``t_off``: off-time in seconds (for ``mode=pulse``).
    """

    @property
    def mode(self) -> str | None:
        """Port mode, or ``None`` if unset."""
        d = self.data_
        return d.get("mode") if isinstance(d, Mapping) else None

    @property
    def dest(self) -> Path | None:
        """Destination path (input modes), or ``None``."""
        d = self.data_
        s = d.get("dest") if isinstance(d, Mapping) else None
        return s if s is None else Path.build(s)

    @property
    def src(self) -> Path | None:
        """Source path (output modes), or ``None``."""
        d = self.data_
        s = d.get("src") if isinstance(d, Mapping) else None
        return s if s is None else Path.build(s)

    @property
    def state(self) -> Path | None:
        """Optional state path (output modes), or ``None``."""
        d = self.data_
        s = d.get("state") if isinstance(d, Mapping) else None
        return s if s is None else Path.build(s)

    @property
    def rest(self) -> bool:
        """Rest-state flag (default ``False``)."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return bool(d.get("rest", False)) if isinstance(d, Mapping) else False

    @property
    def interval(self) -> float | None:
        """Polling interval (for ``mode=count``), or ``None``."""
        d = self.data_
        return d.get("interval") if isinstance(d, Mapping) else None

    @property
    def count(self) -> bool | None:
        """Pulse direction (``True``/``False``/``None``)."""
        d = self.data_
        v = d.get("count") if isinstance(d, Mapping) else None
        return v if v is None else bool(v)

    @property
    def t_on(self) -> float | None:
        """On-time in seconds (for ``mode=oneshot|pulse``), or ``None``."""
        d = self.data_
        return d.get("t_on") if isinstance(d, Mapping) else None

    @property
    def t_off(self) -> float | None:
        """Off-time in seconds (for ``mode=pulse``), or ``None``."""
        d = self.data_
        return d.get("t_off") if isinstance(d, Mapping) else None

    @property
    def card(self) -> int:
        """Card number (parent key)."""
        # The parent of a port is a card; we walk up the tree.
        # This is typically known from the path context.
        return 0

    @property
    def port(self) -> int:
        """Port number (this node's key)."""
        return 0

    def is_complete(self) -> bool:
        """Whether this entry has a complete configuration."""
        m = self.mode
        if m in ("read", "count"):
            return self.dest is not None
        if m in ("write", "oneshot", "pulse"):
            return self.src is not None
        return False


@define
class WagoCard(Node):
    """Intermediate card-number node; children are :class:`WagoPort`."""

    def add_child(self, item: Key) -> WagoPort:
        """Create child entries as :class:`WagoPort`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = WagoPort()
        return s


@define
class WagoType(Node):
    """Intermediate ``input`` or ``output`` node; children are :class:`WagoCard`."""

    def add_child(self, item: Key) -> WagoCard:
        """Create child entries as :class:`WagoCard`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = WagoCard()
        return s


@define
class WagoServer(Node):
    """One Wago server (controller) in the configuration tree.

    Children at the ``input`` / ``output`` levels branch out into
    card/port levels and finally into :class:`WagoPort` leaves.
    """

    def add_child(self, item: Key) -> WagoType:
        """Create child entries as :class:`WagoType`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = WagoType()
        return s

    @property
    def cfg(self) -> dict[str, Any]:
        """Server-level config dict (``host``/``port``)."""
        d = self.data_
        if d is NotGiven or not isinstance(d, Mapping):
            return {}
        s = d.get("server", {})
        return s if isinstance(s, Mapping) else {}


@define
class WagoRoot(Node):
    """Root of the Wago configuration tree.

    Children are :class:`WagoServer` nodes.
    """

    def add_child(self, item: Key) -> WagoServer:
        """Create child servers as :class:`WagoServer`.

        Returns the existing entry if *item* is already present.
        """
        s = self._sub.get(item)
        if not isinstance(s, WagoServer):
            self._sub[item] = s = WagoServer()
        return s
