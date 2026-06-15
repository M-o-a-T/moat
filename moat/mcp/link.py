"""
The MoaT-Link MCP service.

This service connects to a :class:`moat.link.client.Link` and exposes tools
to read and write values and to watch a path for changes.
"""

from __future__ import annotations

import anyio
from contextlib import asynccontextmanager

from attrs import define, field

from moat.util import NotGiven
from moat.lib.path import P, Path

from . import Service as _Service

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskGroup
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )

    from moat.util import attrdict
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator

__all__ = ["LinkMCP", "LinkService", "Service", "Watch"]


def _as_path(path: str | Path) -> Path:
    """Convert a dotted string to a :class:`~moat.lib.path.Path`."""
    if isinstance(path, Path):
        return path
    return P(path)


def _clean(value: Any) -> Any:
    """Convert link sentinels to JSON-friendly values."""
    if value is NotGiven:
        return None
    return value


@define
class Watch:
    """
    State for one active watch.

    A background task feeds change notifications into the queue; the client
    retrieves them via :meth:`LinkMCP.watch_get` and eventually stops the
    watch via :meth:`LinkMCP.watch_stop`.
    """

    path: Path = field()
    subtree: bool = field()
    scope: anyio.CancelScope = field()
    queue_w: MemoryObjectSendStream[dict[str, Any]] = field()
    queue_r: MemoryObjectReceiveStream[dict[str, Any]] = field()
    done: anyio.Event = field(factory=anyio.Event)


class LinkMCP:
    """
    The MoaT-Link MCP backend.

    It wraps a :class:`~moat.link.client.LinkSender` and a task group used to
    run background watch tasks.
    """

    def __init__(self, link: LinkSender, tg: TaskGroup, queue_len: int = 100):
        self._link = link
        self._tg = tg
        self._queue_len = queue_len
        self._watches: dict[int, Watch] = {}
        self._next_id = 0

    async def value_get(self, path: str | Path) -> Any:
        """
        Read the value stored at ``path``.

        Args:
            path: dotted path to read.

        Returns:
            The stored value, or `None` if nothing is stored there.
        """
        try:
            return _clean(await self._link.d_get(_as_path(path)))
        except KeyError:
            return None

    async def value_set(self, path: str | Path, value: Any) -> None:
        """
        Store ``value`` at ``path``.

        Args:
            path: dotted path to write.
            value: the value to store.
        """
        await self._link.d_set(_as_path(path), value)

    async def watch_start(self, path: str | Path, subtree: bool = False) -> int:
        """
        Start watching ``path`` for changes.

        Args:
            path: dotted path to watch.
            subtree: also report changes below ``path``.

        Returns:
            A watch ID, to be passed to :meth:`watch_get` and
            :meth:`watch_stop`.
        """
        p = _as_path(path)
        wid = self._next_id
        self._next_id += 1
        qw, qr = anyio.create_memory_object_stream[dict[str, Any]](self._queue_len)
        watch = Watch(
            path=p,
            subtree=subtree,
            scope=anyio.CancelScope(),
            queue_w=qw,
            queue_r=qr,
        )
        self._watches[wid] = watch
        await self._tg.start(self._run_watch, watch)
        return wid

    async def _run_watch(
        self, watch: Watch, *, task_status: Any = anyio.TASK_STATUS_IGNORED
    ) -> None:
        """Background task that feeds a watch's queue."""
        try:
            with watch.scope:
                async with watch.queue_w:
                    if watch.subtree:
                        await self._feed_subtree(watch, task_status)
                    else:
                        await self._feed_single(watch, task_status)
        finally:
            watch.done.set()

    async def _feed_single(self, watch: Watch, task_status: Any) -> None:
        """Feed change records for a single node."""
        async with self._link.d_watch(watch.path, meta=True) as mon:
            task_status.started()
            async for data, meta in mon:
                self._enqueue(watch, list(watch.path), data, meta)

    async def _feed_subtree(self, watch: Watch, task_status: Any) -> None:
        """Feed change records for a subtree."""
        async with self._link.d_watch(watch.path, mark=False, meta=True, subtree=True) as mon:
            task_status.started()
            async for sub, data, meta in mon:
                self._enqueue(watch, list(watch.path + sub), data, meta)

    @staticmethod
    def _enqueue(watch: Watch, path: list[Any], data: Any, meta: Any) -> None:
        """Append a change record, dropping the oldest item if full."""
        res: dict[str, Any] = {
            "path": path,
            "value": _clean(data),
            "meta": meta.repr() if meta is not None else None,
        }
        try:
            watch.queue_w.send_nowait(res)
        except anyio.WouldBlock:
            # Slow consumer: drop the oldest item, then retry.
            try:
                watch.queue_r.receive_nowait()
            except anyio.WouldBlock:
                pass
            try:
                watch.queue_w.send_nowait(res)
            except anyio.WouldBlock:
                pass

    async def watch_get(
        self, watch_id: int, max_items: int = 0, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve pending change notifications for a watch.

        Args:
            watch_id: the ID returned by :meth:`watch_start`.
            max_items: maximum number of items to return; ``0`` means no
                limit.
            timeout: if no data is pending, wait up to this many seconds for
                the first item. `None` returns immediately.

        Returns:
            A list of change records. Each record is a mapping with ``path``,
            ``value`` and ``meta`` keys. An empty list means no data arrived
            within the timeout.

        Raises:
            KeyError: the watch ID is unknown.
        """
        watch = self._watches[watch_id]
        res: list[dict[str, Any]] = []

        if timeout is not None:
            with anyio.move_on_after(timeout):
                res.append(await watch.queue_r.receive())

        while max_items <= 0 or len(res) < max_items:
            try:
                res.append(watch.queue_r.receive_nowait())
            except anyio.WouldBlock:
                break
        return res

    async def watch_stop(self, watch_id: int) -> None:
        """
        Stop a watch and release its resources.

        Args:
            watch_id: the ID returned by :meth:`watch_start`.

        Raises:
            KeyError: the watch ID is unknown.
        """
        watch = self._watches.pop(watch_id)
        watch.scope.cancel()
        await watch.done.wait()

    async def aclose(self) -> None:
        """Stop all active watches."""
        for wid in list(self._watches):
            with anyio.CancelScope(shield=True):
                await self.watch_stop(wid)


class LinkService(_Service):
    """
    The MoaT-Link MCP service.

    It opens a :class:`~moat.link.client.Link` connection and exposes value
    get/set and path-watching tools.
    """

    name = "link"
    backend: LinkMCP

    def __init__(self, cfg: attrdict, tg: TaskGroup):
        super().__init__(cfg, tg)
        self._queue_len = int(cfg.get("queue_len", 100))

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[LinkService]:
        from moat.lib.config import CFG  # noqa: PLC0415
        from moat.link.client import Link  # noqa: PLC0415

        link_cfg = self.cfg.get("link", None) or CFG.result.moat.link
        async with Link(link_cfg) as link:
            self.backend = LinkMCP(link, self.tg, queue_len=self._queue_len)
            try:
                yield self
            finally:
                with anyio.CancelScope(shield=True):
                    await self.backend.aclose()

    async def register(self, mcp: Any) -> None:
        """Register the link service's tools on ``mcp``."""
        from ._tools import register_link  # noqa: PLC0415

        register_link(mcp, self)


#: The service class, as looked up by :func:`moat.mcp.load_service`.
Service = LinkService
