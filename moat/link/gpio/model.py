"""
Node model for the GPIO controller connector.

The tree mirrors the MoaT-Link subtree under the configured prefix.
Each host entry is keyed by its name; below it the tree branches
into integer line numbers, each holding a :class:`GpioLine` leaf.
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


logger = logging.getLogger(__name__)


@define
class GpioLine(Node):
    """A single GPIO line.

    The stored configuration is a dict with these keys:

    * ``type``: ``"input"`` or ``"output"``.
    * ``mode``: input mode (``"read"``, ``"count"``, ``"button"``) or
      output mode (``"write"``, ``"oneshot"``, ``"pulse"``).
    * ``dest``: destination path (for input modes).
    * ``src``: source path (for output modes).
    * ``state``: optional state path (for output modes).
    * ``low``: active-low flag (default ``False``).
    * ``interval``: polling interval (for ``mode=count``).
    * ``count``: pulse direction (``True``/``False``/``None``).
    * ``t_on``: on-time (for ``mode=oneshot|pulse``).
    * ``t_off``: off-time (for ``mode=pulse``).
    * ``t_bounce``: debounce time.
    * ``t_idle``: max pulse width (for ``mode=button``).
    * ``t_clear``: clear-after time (for ``mode=button``).
    * ``skip``: ignore short bounces.
    * ``flow``: send intermediate results.
    """

    @property
    def type_(self) -> str | None:
        """Line type, or ``None`` if unset."""
        d = self.data_
        return d.get("type") if isinstance(d, Mapping) else None

    @property
    def mode(self) -> str | None:
        """Line mode, or ``None`` if unset."""
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
    def low(self) -> bool:
        """Active-low flag (default ``False``)."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return bool(d.get("low", False)) if isinstance(d, Mapping) else False

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
    def t_bounce(self) -> float | None:
        """Debounce time, or ``None``."""
        d = self.data_
        return d.get("t_bounce") if isinstance(d, Mapping) else None

    @property
    def t_idle(self) -> float | None:
        """Max pulse width (for ``mode=button``), or ``None``."""
        d = self.data_
        return d.get("t_idle") if isinstance(d, Mapping) else None

    @property
    def t_clear(self) -> float | None:
        """Clear-after time (for ``mode=button``), or ``None``."""
        d = self.data_
        return d.get("t_clear") if isinstance(d, Mapping) else None

    @property
    def skip(self) -> bool:
        """Ignore short bounces (default ``True``)."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return bool(d.get("skip", True)) if isinstance(d, Mapping) else True

    @property
    def flow(self) -> bool:
        """Send intermediate results (default ``False``)."""
        d = self.data_ if self.data_ is not NotGiven else {}
        return bool(d.get("flow", False)) if isinstance(d, Mapping) else False

    def is_complete(self) -> bool:
        """Whether this entry has a complete configuration."""
        t = self.type_
        m = self.mode
        if t == "input":
            return m is not None and self.dest is not None
        if t == "output":
            return m is not None and self.src is not None
        return False


@define
class GpioChip(Node):
    """One GPIO chip (controller); children are :class:`GpioLine`."""

    def add_child(self, item: Key) -> GpioLine:
        """Create child entries as :class:`GpioLine`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = GpioLine()
        return s

    @property
    def name(self) -> str | None:
        """Chip name (this node's key, if known from path context)."""
        return None


@define
class GpioHost(Node):
    """One host in the configuration tree; children are :class:`GpioChip`."""

    def add_child(self, item: Key) -> GpioChip:
        """Create child chips as :class:`GpioChip`."""
        if item in self._sub:
            raise ValueError("exists")
        self._sub[item] = s = GpioChip()
        return s


@define
class GpioRoot(Node):
    """Root of the GPIO configuration tree.

    Children are :class:`GpioHost` nodes.
    """

    def add_child(self, item: Key) -> GpioHost:
        """Create child hosts as :class:`GpioHost`."""
        s = self._sub.get(item)
        if not isinstance(s, GpioHost):
            self._sub[item] = s = GpioHost()
        return s
