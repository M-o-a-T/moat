"""
MoaT-Link helpers shared by the heat controller's unit adapters.

See HEAT.md §2.2 (reading inputs, staleness, writing outputs, liveness)
and §2.7 (operator overrides).
"""

from __future__ import annotations

import anyio
import logging

from moat.util import NotGiven
from moat.lib.path import P, Path
from moat.util.time import time

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from moat.link.client import LinkSender

    from collections.abc import Callable

__all__ = [
    "Inputs",
    "Override",
    "Reader",
    "ServiceMonitor",
    "TreeReader",
    "Writer",
    "is_up",
    "out_path",
    "service_path",
]

_logger = logging.getLogger(__name__)

T = TypeVar("T")


def out_path(unit: str) -> Path:
    """The path of a unit's published view, ``app.heat.<unit>.out`` (HEAT.md §2.2)."""
    return P("app.heat") / unit / "out"


def service_path(host: str, unit: str) -> Path:
    """
    The path of a unit's service announcement.

    Args:
        host: The installation-wide host name (see
            :class:`~moat.dev.heat.config.ServiceCfg`).
        unit: The unit's name.
    """
    return P("run.host") / host / "heat" / unit


class Reader(Generic[T]):
    """
    The current value of one MoaT-Link item.

    Start :meth:`run` in a task group. Deleting the item resets
    :attr:`value` to `None`.

    Args:
        link: The MoaT-Link client.
        path: The item to watch.
        on_change: Called whenever the value changes.
    """

    value: T | None
    """The last value, or `None` before the first message."""

    ts: float | None
    """Wall-clock timestamp of :attr:`value`, from its metadata."""

    def __init__(
        self, link: LinkSender, path: Path, on_change: Callable[[], None] | None = None
    ) -> None:
        self.link = link
        self.path = path
        self.on_change = on_change
        self.value = None
        self.ts = None
        # created on demand, so that a reader can be built outside an event
        # loop (the closed-loop test runner feeds readers synchronously)
        self._changed: anyio.Event | None = None

    def feed(self, value: Any, ts: float | None) -> None:
        """Set a new raw value, as if it had arrived from MoaT-Link."""
        self._update(value, ts)

    def _update(self, value: Any, ts: float | None) -> None:
        """Store a new raw value and notify listeners."""
        self.value = None if value is NotGiven else value
        self.ts = ts
        self._notify()

    def _notify(self) -> None:
        if self._changed is not None:
            self._changed.set()
            self._changed = None
        if self.on_change is not None:
            self.on_change()

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """
        Watch the item.

        Signals readiness once the item's current state is known.
        """
        async with self.link.d_watch(self.path, meta=True, mark=True) as mon:
            async for msg in mon:
                if msg is None:
                    task_status.started()
                    continue
                data, meta = msg
                self._update(data, meta.timestamp)

    def fresh(self, now: float, max_age: float) -> bool:
        """
        Check whether the value is recent enough.

        Args:
            now: The current wall-clock time.
            max_age: The maximum acceptable age, in seconds.
        """
        return self.value is not None and self.ts is not None and now - self.ts <= max_age

    async def wait_value(self) -> T:
        """Wait until the item has a value, and return it."""
        while self.value is None:
            await self.wait_changed()
        return self.value

    async def wait_changed(self) -> None:
        """Wait until the value changes."""
        if self._changed is None:
            self._changed = anyio.Event()
        await self._changed.wait()


class TreeReader(Reader[dict[Path, Any]]):
    """
    The current values of all items in a MoaT-Link subtree.

    :attr:`~Reader.value` maps each item's path, relative to the watched
    path, to its value; it is an empty mapping once the subtree is known to
    be empty. :attr:`~Reader.ts` is the timestamp of the latest change.
    """

    def feed(self, value: Any, ts: float | None) -> None:
        """Replace the whole subtree (a mapping of relative paths to values, or `None`)."""
        self._update(None if value is None else dict(value), ts)

    def feed_item(self, path: Path, value: Any, ts: float | None) -> None:
        """
        Set or delete one item, as if it had arrived from MoaT-Link.

        Args:
            path: The item's path, relative to the watched path.
            value: The new value; `None` or `NotGiven` deletes the item.
            ts: The value's timestamp.
        """
        items = dict(self.value or {})
        if value is None or value is NotGiven:
            items.pop(path, None)
        else:
            items[path] = value
        self._update(items, ts)

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """
        Watch the subtree.

        Signals readiness once the subtree's current state is known.
        """
        async with self.link.d_watch(self.path, meta=True, mark=True, subtree=True) as mon:
            async for msg in mon:
                if msg is None:
                    if self.value is None:
                        self._update({}, None)
                    task_status.started()
                    continue
                path, data, meta = msg
                self.feed_item(Path.build(path), data, meta.timestamp)


class Override(Reader[T]):
    """
    An operator override (HEAT.md §2.7).

    The item holds a value, `None` (automatic), or a mapping
    ``{value, expires, reason}``; ``expires`` (wall-clock time) and
    ``reason`` are optional. After ``expires`` the override reads as `None`
    and a change is signalled; with ``clear``, the expired item is also
    deleted, so that every consumer (and the operator's UI) sees it lapse.

    Args:
        kind: The value's type (`bool` or `float`); a value of another
            type reads as `None`, with a warning. `float` accepts ints but
            not booleans.
        clear: Delete the item when it expires.
    """

    reason: str | None
    """The reason given for the override, if any."""

    expires: float | None
    """When the override expires (wall-clock time), if ever."""

    def __init__(
        self,
        link: LinkSender,
        path: Path,
        on_change: Callable[[], None] | None = None,
        *,
        kind: type | None = None,
        clear: bool = False,
    ) -> None:
        super().__init__(link, path, on_change)
        self.reason = None
        self.expires = None
        self.kind = kind
        self.clear = clear
        self._raw: Any = None
        self._timer: anyio.CancelScope | None = None
        self._tg: TaskGroup | None = None

    def _ok(self, value: Any) -> bool:
        if self.kind is None or value is None:
            return True
        if self.kind is float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return isinstance(value, self.kind)

    def _update(self, value: Any, ts: float | None) -> None:
        self._raw = value
        self.reason = None
        self.expires = None
        if isinstance(value, Mapping):
            self.reason = value.get("reason")
            self.expires = value.get("expires")
            value = value.get("value")
            if self.expires is not None and self.expires <= time():
                value = None
        if not self._ok(value):
            _logger.warning("Override %s: not a %s: %r", self.path, self.kind, value)
            value = None
        self._set_timer()
        super()._update(value, ts)

    def _set_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self.expires is not None and self._tg is not None:
            self._timer = anyio.CancelScope()
            self._tg.start_soon(self._expire, self.expires, self._timer)

    async def _expire(self, expires: float, scope: anyio.CancelScope) -> None:
        with scope:
            await anyio.sleep(max(expires - time(), 0))
            if self._timer is scope:
                self._timer = None
            if self.value is not None:
                _logger.info("Override %s expired", self.path)
                self.value = None
                self._notify()
            raw = self._raw
            if self.clear and isinstance(raw, Mapping) and raw.get("expires") == expires:
                # the item is still the expired one: remove it
                with anyio.CancelScope(shield=True):
                    await self.link.d_set(self.path, retain=True, verify=False)

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Watch the item and expire it on time."""
        async with anyio.create_task_group() as tg:
            self._tg = tg
            try:
                await super().run(task_status=task_status)
            finally:
                self._tg = None
                tg.cancel_scope.cancel()


class Inputs:
    """
    A set of named readers, merged into one "something changed" signal.

    Start :meth:`run` in a task group. After it is started, every reader
    knows the current state of its item.

    Args:
        on_change: Also called whenever any input changes.
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self.readers: dict[str, Reader[Any]] = {}
        self.on_change = on_change
        self._changed = anyio.Event()

    def _on_change(self) -> None:
        self._changed.set()
        if self.on_change is not None:
            self.on_change()

    def add(self, name: str, reader: Reader[T]) -> Reader[T]:
        """Add a reader and return it."""
        reader.on_change = self._on_change
        self.readers[name] = reader
        return reader

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Run all readers."""
        async with anyio.create_task_group() as tg:
            for r in self.readers.values():
                await tg.start(r.run)
            task_status.started()

    async def wait(self) -> None:
        """Wait until any input changes (or has changed since the last call)."""
        await self._changed.wait()
        self._changed = anyio.Event()

    def snapshot(self) -> dict[str, Any]:
        """The current value of every input, by name."""
        return {k: r.value for k, r in self.readers.items()}


class Writer:
    """
    Writes retained values, skipping writes that would not change anything.

    This replaces MoaT-KV's ``idem=True``.

    Args:
        link: The MoaT-Link client.
    """

    def __init__(self, link: LinkSender) -> None:
        self.link = link
        self._last: dict[Path, Any] = {}

    async def set(self, path: Path, value: Any, force: bool = False) -> bool:
        """
        Write a value unless it's the same as the last one written.

        Args:
            path: The item to write.
            value: The new value.
            force: Write even if the value is unchanged.

        Returns:
            Whether the value was written.
        """
        if not force and path in self._last and self._last[path] == value:
            return False
        await self.link.d_set(path, value, retain=True)
        self._last[path] = value
        return True


def is_up(announcement: Any) -> bool:
    """
    Whether a service announcement says the service is up.

    Args:
        announcement: The value of a ``run.host.<host>.…`` item, or `None`.
    """
    return isinstance(announcement, Mapping) and bool(announcement.get("up"))


class ServiceMonitor(Reader[Any]):
    """
    Tracks whether a unit's service is alive, from its announcement.

    Args:
        link: The MoaT-Link client.
        host: The installation-wide host name.
        unit: The unit to monitor.
        on_change: Called whenever the announcement changes.
    """

    def __init__(
        self, link: LinkSender, host: str, unit: str, on_change: Callable[[], None] | None = None
    ) -> None:
        super().__init__(link, service_path(host, unit), on_change)

    @property
    def alive(self) -> bool:
        """Whether the service is announced and up."""
        return is_up(self.value)
