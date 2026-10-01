"""
Data model for the 1-Wire (OWFS) bus connector.

The configuration lives below the ``link.ow.prefix`` path (default
``1wire``). 1-Wire device IDs are globally unique, so the configuration
is keyed by device, not by bus: a device may move to another bus and
keeps its settings.

* ``FAMILY``: settings common to all devices of this family code.
* ``FAMILY.CODE``: settings for one device.
* ``FAMILY.CODE.ATTR…``: one attribute mapping.
* ``server.NAME``: one owserver, ``{server: {host, port}}``.

``FAMILY`` and ``CODE`` are stored as integers but always shown as two
and twelve hex digits.

An attribute mapping's effective configuration is its own data, merged
over its device's, merged over its family's. It mirrors in one
direction:

* **read** (``dest`` set): the device attribute is polled every
  ``interval`` seconds and its value is published to ``dest``.
* **write** (``src`` set): ``src`` is watched and its value is written to
  the device attribute.

``dest_attr`` / ``src_attr`` select a nested field of the transferred
value; ``idem`` (default ``True``) controls idempotent publishing.
"""

from __future__ import annotations

import logging
import re

from attrs import define

from moat.util import NotGiven, combine_dict
from moat.lib.path import P, Path
from moat.link.node import Node

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Key

    from typing import Any

logger = logging.getLogger(__name__)

SERVER = "server"
"Below the prefix: the owserver entries."

_FAMILY = re.compile(r"^[0-9a-fA-F]{1,2}$")
_CODE = re.compile(r"^[0-9a-fA-F]{1,12}$")


def fmt_family(family: int) -> str:
    """Display a family code: two hex digits."""
    return f"{family:02x}"


def fmt_code(code: int) -> str:
    """Display a device code: twelve hex digits."""
    return f"{code:012x}"


def fmt_device(family: int, code: int) -> str:
    """Display a device: ``FAMILY.CODE``."""
    return f"{fmt_family(family)}.{fmt_code(code)}"


def parse_at(spec: str) -> tuple[int, int | None, Path]:
    """Parse ``FAMILY[.CODE[.ATTR…]]``.

    FAMILY and CODE are hex numbers (at most 2 and 12 digits). The rest,
    if any, is the attribute path, in `moat.lib.path.P` syntax.

    Returns:
        ``(family, code, attr)``. *code* is ``None`` if not given; *attr*
        is empty unless a code is given.

    Raises:
        ValueError: on a malformed family or code.
    """
    fam, dot, rest = spec.partition(".")
    if not _FAMILY.match(fam):
        raise ValueError(f"Not a 1-Wire family code (two hex digits): {fam!r}")
    if not dot:
        return int(fam, 16), None, Path()
    code, _, attr = rest.partition(".")
    if not _CODE.match(code):
        raise ValueError(f"Not a 1-Wire device code (twelve hex digits): {code!r}")
    return int(fam, 16), int(code, 16), P(attr) if attr else Path()


def _mapping(d: Any) -> Mapping:
    return d if isinstance(d, Mapping) else {}


@define
class AttrCfg:
    """The effective configuration of one attribute mapping."""

    dest: Path | None = None
    "Destination path (read direction)."
    src: Path | None = None
    "Source path (write direction)."
    interval: float | None = None
    "Polling interval in seconds (read direction)."
    dest_attr: Path | None = None
    "Sub-attribute merged into ``dest``'s value."
    src_attr: Path | None = None
    "Sub-attribute extracted from ``src``'s value."
    idem: bool = True
    "Idempotency flag."

    @classmethod
    def build(cls, *data: Any) -> AttrCfg:
        """Build from attr, device and family data (the first one wins)."""
        d = combine_dict(*(_mapping(x) for x in data))

        def _p(k):
            v = d.get(k)
            return None if v is None else Path.build(v)

        return cls(
            dest=_p("dest"),
            src=_p("src"),
            interval=d.get("interval"),
            dest_attr=_p("dest_attr"),
            src_attr=_p("src_attr"),
            idem=bool(d.get("idem", True)),
        )

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
class OwAttr(Node):
    """An attribute mapping (or an intermediate attribute path element)."""

    def add_child(self, item: Key) -> OwAttr:
        """Nested attribute path elements are :class:`OwAttr` nodes too."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwAttr()
        return s


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
    """A family code; children are :class:`OwDevice`."""

    def add_child(self, item: Key) -> Node:
        """Integer children are devices."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwDevice() if isinstance(item, int) else Node()
        return s


@define
class OwServer(Node):
    """One owserver."""

    @property
    def cfg(self) -> dict[str, Any]:
        """The ``host``/``port`` settings."""
        return dict(_mapping(_mapping(self.data_).get(SERVER)))


@define
class OwServers(Node):
    """The ``server`` subtree; children are :class:`OwServer`."""

    def add_child(self, item: Key) -> OwServer:
        """Create child entries as :class:`OwServer`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = OwServer()
        return s


@define
class OwRoot(Node):
    """Root of the 1-Wire configuration tree.

    Integer children are :class:`OwFamily` nodes; the ``server`` child
    holds the owservers.
    """

    def add_child(self, item: Key) -> Node:
        """Create typed children."""
        if item in self._sub:
            raise ValueError(f"exists: {item!r}")
        if isinstance(item, int):
            s: Node = OwFamily()
        elif item == SERVER:
            s = OwServers()
        else:
            s = Node()
        self._sub[item] = s
        return s

    def attr_cfg(self, family: int, code: int, attr: Path) -> AttrCfg | None:
        """The effective configuration of an attribute mapping.

        Returns ``None`` if the mapping doesn't exist.
        """
        try:
            fam = self.get(family, create=False)
            dev = fam.get(code, create=False)
            node = dev.get(attr, create=False)
        except KeyError:
            return None
        if node.data_ is NotGiven:
            return None
        return AttrCfg.build(node.data_, dev.data_, fam.data_)

    def attrs(self, family: int, code: int | None = None):
        """Yield ``(family, code, attr)`` of the mappings below a family or device."""
        try:
            fam = self.get(family, create=False)
        except KeyError:
            return
        for c, dev in fam:
            if not isinstance(c, int) or (code is not None and c != code):
                continue
            yield from ((family, c, a) for a in _attr_paths(dev, Path()))


def _attr_paths(node: Node, prefix: Path):
    for k, sub in node:
        p = prefix / k
        if sub.data_ is not NotGiven:
            yield p
        yield from _attr_paths(sub, p)
