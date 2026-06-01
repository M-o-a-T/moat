"""
Node model for the KNX bus connector.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each server entry is keyed by its name; below it the tree branches
along the three integer components of a KNX group address
(``main``/``middle``/``sub``).
"""

from __future__ import annotations

import logging

from attrs import define

from moat.util import NotGiven
from moat.lib.path import Path
from moat.lib.xknx.telegram import GroupAddress
from moat.link.node import Node

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Key

    from collections.abc import Mapping
    from typing import Any

logger = logging.getLogger(__name__)


def parse_group(addr: str) -> tuple[int, int, int]:
    """Parse a KNX ``a/b/c`` group address into a 3-tuple of integers.

    Args:
        addr: A KNX group address string, e.g. ``"1/2/3"``.

    Returns:
        ``(main, middle, sub)`` as a 3-tuple of ``int``.

    Raises:
        ValueError: if *addr* is not a valid 3-part group address.
    """
    if addr.count("/") != 2:
        raise ValueError(f"Not a 3-part KNX group address: {addr!r}")
    ga = GroupAddress(addr)
    main, middle, sub = ga.main, ga.middle, ga.sub
    if main is None or middle is None or sub is None:
        raise ValueError(f"Not a 3-part KNX group address: {addr!r}")
    return (main, middle, sub)


def group_subpath(addr: str) -> Path:
    """Return *addr* as a 3-element :class:`~moat.lib.path.Path`."""
    return Path.build(parse_group(addr))


@define
class KnxEntry(Node):
    """A single KNX group-address mapping.

    Maps one KNX group address to a MoaT-Link source/destination path.
    The stored configuration is a dict with these keys:

    * ``type``: ``"in"`` (KNX → Link) or ``"out"`` (Link → KNX).
    * ``mode``: XKNX data-point type, e.g. ``"binary"`` or ``"Bool"``.
    * ``src``: source path (for ``type=out``).
    * ``dest``: destination path (for ``type=in``).
    * ``idem``: optional idempotency flag (default ``True``).
    """

    @property
    def type_(self) -> str | None:
        """``in`` or ``out`` direction, or ``None`` if unset."""
        d = self.data_
        return d.get("type") if isinstance(d, dict) else None

    @property
    def mode(self) -> str | None:
        """XKNX data-point type name, or ``None`` if unset."""
        d = self.data_
        return d.get("mode") if isinstance(d, dict) else None

    @property
    def src(self) -> Path | None:
        """Source path (for ``type=out``), or ``None``."""
        d = self.data_
        s = d.get("src") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def dest(self) -> Path | None:
        """Destination path (for ``type=in``), or ``None``."""
        d = self.data_
        s = d.get("dest") if isinstance(d, dict) else None
        return s if s is None else Path.build(s)

    @property
    def idem(self) -> bool:
        """Whether to skip writes when the value is unchanged."""
        d = self.data_ if self.data_ is not NotGiven else {}
        if not isinstance(d, dict):
            return True
        return bool(d.get("idem", True))

    def is_complete(self) -> bool:
        """Whether this entry has a complete configuration."""
        t = self.type_
        if t == "in":
            return self.mode is not None and self.dest is not None
        if t == "out":
            return self.mode is not None and self.src is not None
        return False


@define
class KnxMiddle(Node):
    """Intermediate ``middle`` group-address node; children are :class:`KnxEntry`."""

    def add_child(self, item: Key) -> KnxEntry:
        """Create child entries as :class:`KnxEntry`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = KnxEntry()
        return s


@define
class KnxMain(Node):
    """Intermediate ``main`` group-address node; children are :class:`KnxMiddle`."""

    def add_child(self, item: Key) -> KnxMiddle:
        """Create child entries as :class:`KnxMiddle`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = KnxMiddle()
        return s


@define
class KnxServer(Node):
    """One KNX server (gateway) in the configuration tree.

    Children at the integer ``main`` level branch out into
    middle/sub levels and finally into :class:`KnxEntry` leaves.
    """

    def add_child(self, item: Key) -> KnxMain:
        """Create child entries as :class:`KnxMain`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = KnxMain()
        return s

    @property
    def cfg(self) -> Mapping[str, Any]:
        """Server-level config dict (``host``/``port``)."""
        d = self.data_
        if d is NotGiven or not isinstance(d, dict):
            return {}
        s = d.get("server", {})
        return s if isinstance(s, dict) else {}


@define
class KnxRoot(Node):
    """Root of the KNX configuration tree.

    Children are :class:`KnxServer` nodes.
    """

    def add_child(self, item: Key) -> KnxServer:
        """Create child servers as :class:`KnxServer`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = KnxServer()
        return s
