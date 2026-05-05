"""
Gateway to wherever
"""

from __future__ import annotations

import anyio
import logging
import time
from anyio import Lock
from contextlib import suppress

from attrs import define, field

from moat.util import NotGiven, to_attrdict
from moat.lib.codec import get_codec
from moat.lib.path import P, Path
from moat.lib.priomap import TimerMap
from moat.link.meta import MsgMeta
from moat.link.node import Node

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from anyio.abc import TaskGroup

    from moat.util import attrdict
    from moat.lib.codec import Codec
    from moat.link.client import Link, Watcher

    from typing import Any

__all__ = ["DelayedGate", "Gate", "GateNode"]


class GateVanished(RuntimeError):
    "internal error: gate got dropped, or driver changed"

    pass


@define
class GateNode(Node):
    """
    A gatewayed node. It also stores the external value and metadata
    in order to resolve bidirectional updates and/or update conflicts.
    """

    ext_meta: Any = field(init=False, default=None)
    ext_data: Any = field(init=False, default=NotGiven)
    lock: Lock = field(init=False, factory=Lock)

    todo: bool = field(init=False, default=False)
    src_write_time: float = field(init=False, default=0.0)

    @property
    def has_src(self):
        "Check whether source (i.e. MoaT-Link) data is present"
        return self.data_ is not NotGiven or self.meta not in (None, NotGiven)

    @property
    def has_dst(self):
        "Check whether destination (i.e. external) data is present"
        return self.ext_data is not NotGiven or self.ext_meta not in (None, NotGiven)

    @property
    def has_both(self):
        "Check whether both source and destination data are present"
        if self.data_ is NotGiven and self.meta is None:
            return False
        if self.ext_data is NotGiven and self.ext_meta is None:
            return False
        return True

    def clear_src(self, write_time: float = 0.0) -> None:
        """Mark source data as absent, optionally recording the write timestamp."""
        self._data = NotGiven
        self._meta = None
        if write_time:
            self.src_write_time = write_time


@define
class _DelayedUpdate:
    """
    A delayed update entry that hashes to its path.

    Used with TimerMap to delay updates and cancel them if a matching
    update arrives from the other direction.
    """

    path: Path = field()
    data: Any = field()
    meta: MsgMeta | None = field()
    node: GateNode = field()
    to_dst: bool = field(default=False)  # True if this update is going to destination

    def __hash__(self):
        return hash((self.path, self.to_dst))

    def __eq__(self, other: object):
        if isinstance(other, _DelayedUpdate):
            return self.path == other.path and self.to_dst == other.to_dst
        if isinstance(other, tuple) and len(other) == 2:
            return self.path == other[0] and self.to_dst == other[1]
        return False


class Gate:
    """
    This is the base class for data gateways.

    Gateways are described by a dict in ``:R.gate.NAME`` with the following
    entries:

    * src: source path, in *MoaT-Link*.
    * dst: destination (=external data), *must not* be at or under the
      *MoaT-Link* root (if on MQTT) * driver:
      * kv: the destination is MoaT-KV legacy storage
      * mqtt: the destination is a raw MQTT topic (or tree of topics)
    * codec: Encoding of the destination (source is always ``std-cbor``).
    * retain: ``True/False/None``; the latter is the default and copies
      the data's retain flag

    The gateway works thus:
    * if a data item is not in the source or arrives from dest, copy to source
    * if a data item is not in the destination or arrives from source, copy to dest
    * if the values are equal, do nothing
    * if the source metadata say the data is from the destination, copy dest to source
    * otherwise copy source to dest.

    Subclasses override
    * `get_dst`
    * `set_dst`
    * `newer_dst`
    * `is_update`
    * `run_` (if required)
    """

    state: Node
    src: Node
    data: GateNode
    tg: TaskGroup
    codec: Codec

    _waiting: TimerMap[_DelayedUpdate]
    _speed: float = 0
    _speed_pending: dict[tuple[Path, bool], _DelayedUpdate]

    _src_done: anyio.Event
    _dst_done: anyio.Event

    cfg: attrdict
    cf: attrdict

    def __init__(self, cfg: dict[str, Any], cf: dict[str, Any], path: Path, link: Link):
        """
        Setup.
        @cfg: initial data for this gateway.
        """
        self.cfg = cfg
        self.cf = to_attrdict(cf)
        self.codec = cf.get("codec", "cbor")
        if isinstance(self.codec, str):
            self.codec = get_codec(self.codec)

        self.link = link
        self.path = path
        self.origin = str(
            Path.build(("GATE",) + (P(cf["name"]) if "name" in cf else self.path[1:]))
        )
        self._waiting = TimerMap()
        self._speed_pending = {}
        self._speed = float(self.cf.get("speed", 0))

        self.logger = logging.getLogger(f"moat.link.{path}")

    async def get_src(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Fetch the internal data.
        """
        async with self.link.d_watch(
            self.cf.src, subtree=True, state=None, meta=True, mark=True
        ) as mon:
            task_status.started()
            async for pdm in mon:
                if pdm is None:
                    self._src_done.set()
                    continue
                p, d, m = pdm
                if m is not None and m.origin == self.origin and self._src_done.is_set():
                    # mine, so skip
                    continue

                node = cast(GateNode, self.data.get(p))
                if self.running or node.has_src:
                    # self.logger.debug("S NOW %r %r %r",p,d,m)
                    await self._set_dst(p, node, d, m)
                else:
                    # self.logger.debug("S DLY %r %r %r",p,d,m)
                    node.set_(p, d, m)
                    node.todo = True

    async def _set_dst(self, path: Path, node: GateNode, data: Any, meta: MsgMeta):
        node.ext_data = NotGiven
        node.ext_meta = NotGiven
        node.set_(path, data, meta)
        node.todo = False

        async with node.lock:
            await self.set_dst(path, data, meta, node)

    def dst_is_current(self):
        "Must be called when the initial destination data has been read"
        self._dst_done.set()

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        A task that fetches external data.

        Override this. Call `set_src` with each item you discover.

        You must call `dst_is_current` when the current state has been read
        and you're now waiting for updates. If your backend doesn't support
        this, use a timeout *and* an update counter; `set_src` returns True

        """
        raise NotImplementedError

    async def set_src(self, path: Path, data: Any, aux: MsgMeta, speed: float | None = None):
        """
        Update source state (possibly). @aux is additional metadata that
        the destination resolver can use to disambiguate.
        """
        if speed is None:
            speed = self._speed

        node = cast(GateNode, self.data.get(path))

        if self.running or node.has_dst:
            ts = max(
                node.src_write_time,
                node.meta.timestamp if node.meta is not None else 0.0,
            )
            if speed and ts and (tm := ts + speed - time.time()) > 0:
                key = (path, False)
                existing = self._speed_pending.get(key)
                if existing is not None:
                    existing.data = data
                    existing.meta = aux
                    self._waiting.update(existing, tm)
                else:
                    update = _DelayedUpdate(path=path, data=data, meta=aux, node=node)
                    self._speed_pending[key] = update
                    self._waiting[update] = tm

            else:
                await self._set_src(self.cf.src + path, node, data, aux)
        else:
            node.ext_data = data
            node.ext_meta = aux or NotGiven
            node.todo = True

    async def _set_src(self, path: Path, node: GateNode, data: Any, aux: MsgMeta | None):
        async with node.lock:
            if not self.is_update(node, data, aux):
                return
            meta = MsgMeta(origin=self.origin)
            if aux not in (None, NotGiven):
                meta["gw"] = aux

            await self.link.d_set(path, data, meta)

            node.clear_src(write_time=meta.timestamp)
            node.ext_data = data
            node.ext_meta = aux or NotGiven
            node.todo = False

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta | None, node: GateNode):
        """
        Called to update the destination state. @meta is the source
        metadata, in case it is useful in some way.

        You need to override this.
        """
        raise NotImplementedError

    def is_update(self, node: GateNode, data: Any, aux: MsgMeta | None):  # noqa: ARG002
        """
        Check whether this new destination data is an update.

        You probably want to override this.
        """
        return True

    def newer_dst(self, node) -> bool | None:
        """
        Test whether the destination data is newer, based on the node's
        metadata. Must return `True` if the data should be copied to the source,
        `False` if the source should be copied to the destination, or
        `None` if inconclusive.

        This method is only called when starting up.

        You need to override this.
        """
        raise NotImplementedError

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Run a bidirectional copy.

        This method auto-restarts the gateway if its data changes.
        It ends if the gateway node is removed or the driver changes.

        The task status is set when the initial sync has completed.

        Called by the system.
        """
        run = True
        while run:
            self.state = Node()
            self.data = GateNode()
            self._src_done = anyio.Event()
            self._dst_done = anyio.Event()
            self.running = False

            try:
                async with anyio.create_task_group() as self.tg:
                    await self.tg.start(self._restart)
                    await self.run_(task_status=task_status)
            except* GateVanished:
                run = False
            else:
                task_status = anyio.TASK_STATUS_IGNORED
                await anyio.sleep(1)

    async def _restart(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Restart the thing when the root changes."
        async with self.link.d_watch(self.path) as mon:
            task_status.started()
            async for d in mon:
                if self.cf == d:
                    continue
                if d is NotGiven or d.get("driver") != self.cf.driver:
                    raise GateVanished(str(self.path))
                self.cf = d
                self.tg.cancel_scope.cancel()
                return

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        The core runner for the gateway.

        If your implementation needs a context or a support task,
        wrap this method.

        The ``tg`` attribute can be used if you need a taskgroup.
        """
        # start initial loops
        await self.tg.start(self.get_src)
        await self.tg.start(self.get_dst)

        # wait for initial scans to be done
        await self._src_done.wait()
        await self._dst_done.wait()
        self.running = True

        # resolve any conflicts in the initial data
        async def visit(path: Path, node: Node):
            node = cast(GateNode, node)
            if not node.todo:
                return

            if not node.has_src:
                # no source data
                if not node.has_dst:
                    # no destination data
                    return

                # copy dest to source
                d = True

            elif not node.has_dst:
                # copy source to dest
                d = False

            else:
                # both are set. Ugh.
                d = self.newer_dst(node)

            if d is False:
                self.logger.debug("SRC %s %s %r/%r", self.path, path, node.data_, node.meta)
                meta = node.meta
                if meta is None:
                    raise TypeError(f"Missing metadata for source value at {self.path + path}")
                await self._set_dst(path, node, node.data_, meta)

            elif d is True:
                self.logger.debug("DST %s %s %r/%r", self.path, path, node.ext_data, node.ext_meta)

                meta = MsgMeta(origin=self.origin)
                if node.ext_meta:
                    meta["gw"] = node.ext_meta
                await self.link.d_set(self.cf.src + path, node.ext_data, meta)

            elif node.data_ != node.ext_data:
                self.logger.warning(
                    "Conflict %s %s %r/%r vs %r/%r",
                    self.path,
                    path,
                    node.data_,
                    node.meta,
                    node.ext_data,
                    node.ext_meta,
                )

        await self.data.walk(visit, force=True)
        self.tg.start_soon(self._process_pending, self._waiting)
        task_status.started()

    async def state_updater(self, mon: Watcher, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Status update handler.

        By default this just gets the monitor node and updates the raw
        node data in the background.
        """
        node = await mon.get_node()
        task_status.started(node)

        # nothing further to do

    async def _process_pending(self, queue: TimerMap[_DelayedUpdate]) -> None:
        """
        Background task that processes pending updates when their timers expire.
        """
        async for update in queue:
            try:
                if update.to_dst:
                    # Send to destination
                    update.node.ext_data = NotGiven
                    update.node.ext_meta = NotGiven
                    meta = update.meta if update.meta is not None else MsgMeta(origin=self.origin)
                    update.node.set_(update.path, update.data, meta)
                    update.node.todo = False

                    async with update.node.lock:
                        await self.set_dst(update.path, update.data, meta, update.node)
                else:
                    # Send to source
                    async with update.node.lock:
                        if not self.is_update(update.node, update.data, update.meta):
                            continue
                        meta = MsgMeta(origin=self.origin)
                        if update.meta not in (None, NotGiven):
                            meta["gw"] = update.meta

                        await self.link.d_set(self.cf.src + update.path, update.data, meta)

                        self._speed_pending.pop((update.path, False), None)
                        update.node.clear_src(write_time=meta.timestamp)
                        update.node.ext_data = update.data
                        update.node.ext_meta = update.meta or NotGiven
                        update.node.todo = False
            except AttributeError:
                # Connection is being closed during shutdown, ignore
                return


class DelayedGate(Gate):
    """
    A gate that delays update messages.

    This gate delays updates by a configurable time (default 100ms).
    If an update for the same path arrives from the other direction
    before the delay expires, the pending update is cancelled.

    This is useful for network split recovery where the same data
    may be updated on both sides.

    Configuration:
        delay: float - delay in seconds (default 0.1)
    """

    _pending: TimerMap[_DelayedUpdate]
    _delay: float

    def __init__(self, cfg: dict[str, Any], cf: dict[str, Any], path: Path, link: Link):
        super().__init__(cfg, cf, path, link)
        self._delay = cf.get("delay", 0.1)
        self._pending = TimerMap()

    async def _set_dst(self, path: Path, node: GateNode, data: Any, meta: MsgMeta | None):
        """
        Queue an update to the destination, with delay.
        """
        # Cancel any pending update from the other direction for the same path
        with suppress(KeyError):
            del self._pending[(path, False)]  # ty:ignore[invalid-argument-type]

        update = _DelayedUpdate(path=path, data=data, meta=meta, node=node, to_dst=True)
        self._pending[update] = self._delay

    async def _set_src(self, path: Path, node: GateNode, data: Any, aux: MsgMeta | None):
        """
        Queue an update to the source, with delay.

        Note: path here is the full path (cf.src + relative), while _set_dst gets
        relative paths. We need to compute the relative path for consistent lookup.
        """
        # Compute relative path by removing the cf.src prefix
        rel_path = path[len(self.cf.src) :]

        # Cancel any pending update from the other direction for the same path
        with suppress(KeyError):
            del self._pending[(rel_path, True)]  # ty:ignore[invalid-argument-type]

        update = _DelayedUpdate(path=rel_path, data=data, meta=aux, node=node, to_dst=False)
        self._pending[update] = self._delay

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Run the gateway with pending update processing.
        """
        self.tg.start_soon(self._process_pending, self._pending)
        await super().run_(task_status=task_status)


async def run_gate(
    cfg: dict, link: Link, cf: Path | str, *, task_status=anyio.TASK_STATUS_IGNORED
):
    """
    Run a gate in @link, described by @name.
    """
    from importlib import import_module  # noqa: PLC0415

    if isinstance(cf, str):
        cf = P("gate") / cf
    path = cf
    cf = await link.d_get(path)

    drv = cf["driver"]
    if "." not in drv:
        drv = "moat.link.gate." + drv
    gate = import_module(drv).Gate(cfg, cf, path, link)
    await gate.run(task_status=task_status)
