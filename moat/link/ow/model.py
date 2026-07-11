"""
Node model for the 1-Wire (OWFS) bus connector.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each server entry is keyed by its name; below it the tree branches
into the device's family code (a byte), then the device's 48-bit
hardware code, and finally the attribute path that selects the
1-Wire value to mirror.

A single attribute entry can mirror in either direction:

* **read** (``dest`` set): the device attribute is polled and its value
  is published to the MoaT-Link path ``dest``.
* **write** (``src`` set): a MoaT-Link path ``src`` is watched and its
  value is written to the device attribute.

Both directions accept an optional sub-attribute path (``dest_attr`` /
``src_attr``) that selects, or merges into, a nested field of the
transferred value.
"""

from __future__ import annotations

import logging

from attrs import define

from moat.util import NotGiven
from moat.lib.path import Path
from moat.link.node import Node

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Key

    from typing import Any

logger = logging.getLogger(__name__)


def parse_device(addr: str) -> tuple[int, int]:
    """Split a 1-Wire device id ``FF.CODE.CHECK`` into ``(family, code)``.

    Args:
        addr: A device id such as ``"10.345678.90"``.  The family and code
            components are interpreted as hexadecimal; the trailing
            checksum is discarded.

    Returns:
        ``(family, code)`` as a pair of ``int``.

    Raises:
        ValueError: if *addr* is not a 3-part dotted device id.
    """
    parts = addr.split(".")
    if len(parts) != 3:
        raise ValueError(f"Not a 3-part 1-Wire device id: {addr!r}")
    return int(parts[0], 16), int(parts[1], 16)


def device_subpath(addr: str) -> Path:
    """Return the ``(family, code)`` subpath for a 1-Wire device id."""
    f, c = parse_device(addr)
    return Path.build((f, c))


@define
class OwAttr(Node):
    """A single 1-Wire attribute mapping.

    The stored configuration is a dict with these keys:

    * ``dest``: destination MoaT-Link path (read direction).
    * ``src``: source MoaT-Link path (write direction).
    * ``interval``: polling interval in seconds (read direction).
    * ``dest_attr``: sub-attribute path merged into ``dest``'s value.
    * ``src_attr``: sub-attribute path extracted from ``src``'s value.
    * ``idem``: idempotency flag (default ``True``).
    """

    def add_child(self, item: Key) -> OwAttr:
        """Nested attribute segments are :class:`OwAttr` nodes too."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwAttr()
        return s

    @property
    def dest(self) -> Path | None:
        """Destination path (read direction), or ``None``."""
        d = self.data_
        s = d.get("dest") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def src(self) -> Path | None:
        """Source path (write direction), or ``None``."""
        d = self.data_
        s = d.get("src") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def interval(self) -> float | None:
        """Polling interval in seconds (read direction), or ``None``."""
        d = self.data_
        return d.get("interval") if isinstance(d, dict) else None

    @property
    def dest_attr(self) -> Path | None:
        """Sub-attribute merged into ``dest``'s value, or ``None``."""
        d = self.data_
        s = d.get("dest_attr") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def src_attr(self) -> Path | None:
        """Sub-attribute extracted from ``src``'s value, or ``None``."""
        d = self.data_
        s = d.get("src_attr") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def idem(self) -> bool:
        """Idempotency flag (default ``True``)."""
        d = self.data_ if self.data_ is not NotGiven else {}
        if not isinstance(d, dict):
            return True
        return bool(d.get("idem", True))

    @property
    def is_read(self) -> bool:
        """Whether this entry mirrors device→Link (``dest`` is set)."""
        return self.dest is not None

    @property
    def is_write(self) -> bool:
        """Whether this entry mirrors Link→device (``src`` is set)."""
        return self.src is not None

    def is_complete(self) -> bool:
        """Whether this entry has a usable direction."""
        return self.is_read or self.is_write


@define
class OwDevice(Node):
    """One 1-Wire device; children are :class:`OwAttr`."""

    def add_child(self, item: Key) -> OwAttr:
        """Create child entries as :class:`OwAttr`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwAttr()
        return s


@define
class OwFamily(Node):
    """Intermediate family-code node; children are :class:`OwDevice`."""

    def add_child(self, item: Key) -> OwDevice:
        """Create child entries as :class:`OwDevice`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwDevice()
        return s


@define
class OwServer(Node):
    """One OWFS server (owserver) in the configuration tree.

    Children at the integer ``family`` level branch out into
    code/attribute levels and finally into :class:`OwAttr` leaves.
    """

    def add_child(self, item: Key) -> OwFamily:
        """Create child entries as :class:`OwFamily`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwFamily()
        return s

    @property
    def cfg(self) -> dict[str, Any]:
        """Server-level config dict (``host``/``port``)."""
        d = self.data_
        if d is NotGiven or not isinstance(d, dict):
            return {}
        s = d.get("server", {})
        return s if isinstance(s, dict) else {}


@define
class OwRoot(Node):
    """Root of the 1-Wire configuration tree.

    Children are :class:`OwServer` nodes.
    """

    def add_child(self, item: Key) -> OwServer:
        """Create child servers as :class:`OwServer`."""
        if item in self._sub:
            raise ValueError(f"exists: {item!r}")
        self._sub[item] = s = OwServer()
        return s
