"""
Background job runner for MoaT-Link.

This is a streamlined, link-native re-implementation of the job runner
that ``moat kv job`` provides.

Static job data is stored as a subtree under the configured ``prefix``
(default ``job``); dynamic run state is stored under ``state`` (default
``run.job``).  Code snippets executed by jobs are resolved through
:meth:`moat.link.client.LinkSender.code_at`.

Three coordination modes are available (mirroring the kv runner):

* :class:`AnyJobRunner` - exactly one cluster member runs each job.
* :class:`SingleJobRunner` - each job runs on a specific named node.
* :class:`AllJobRunner` - each job runs on every node.
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from asyncactor import AuthPingEvent, NodeList, PingEvent, TagEvent, UntagEvent

from moat.util import NotGiven, attrdict, combine_dict, create_queue, digits
from moat.lib.path import P, Path, logger_for
from moat.util.spawn import spawn

from .actor import (
    ActorState,
    BrokenState,
    CompleteState,
    DetachedState,
    LinkActor,
    PartialState,
)

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from anyio.abc import TaskGroup

    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator, Awaitable, Callable


logger = logging.getLogger(__name__)

QLEN = 10


__all__ = [
    "AllJobRunner",
    "AnyJobRunner",
    "CallAdmin",
    "ChangeMsg",
    "ErrorRecorded",
    "JobEntry",
    "JobRunner",
    "MQTTmsg",
    "ReadyMsg",
    "RunnerMsg",
    "SingleJobRunner",
    "StateEntry",
    "TimerMsg",
    "debug_run",
]


class NotSelected(RuntimeError):
    """This node hasn't been selected for a very long time."""


class ErrorRecorded(RuntimeError):
    """Raised by :meth:`CallAdmin.error` after recording an error.

    Code is not expected to catch this exception.
    """


class RunnerMsg(ActorState):
    """Base class for runner-generated messages.

    Subclasses carry an opaque ``msg`` attribute.
    """


class ChangeMsg(RunnerMsg):
    """A subscribed link entry has been updated.

    The runner also sets ``path`` and ``value`` attributes.
    """

    value: Any = None
    path: Path | None = None


class MQTTmsg(RunnerMsg):
    """An MQTT message has arrived.

    ``value`` is the decoded payload (when decodable). ``path`` is the
    full topic the message was sent to.
    """

    value: Any = None
    path: Path | None = None


class ReadyMsg(RunnerMsg):
    """All initial-state watchers have finished their initial transmission."""


class TimerMsg(RunnerMsg):
    """A timer set up via :meth:`CallAdmin.timer` has fired."""


_CLASSES: attrdict = attrdict()
for _c in (
    DetachedState,
    PartialState,
    CompleteState,
    ActorState,
    BrokenState,
    TimerMsg,
    ReadyMsg,
    ChangeMsg,
    MQTTmsg,
    RunnerMsg,
    ErrorRecorded,
):
    _CLASSES[_c.__name__] = _c

_CLASSES["NotGiven"] = NotGiven


def _split_subpath(p: Path) -> tuple:
    """Convert a `Path` to a hashable tuple key."""
    return tuple(p)


class StateEntry:
    """Dynamic per-job run state.

    Persisted at ``<state_prefix>/<subpath>``.  Direct writes from
    anything other than the runner that owns the job will confuse the
    scheduler.
    """

    ATTRS: ClassVar[tuple[str, ...]] = (
        "started",
        "stopped",
        "pinged",
        "computed",
        "reason",
        "result",
        "node",
        "backoff",
    )

    started: float = 0
    stopped: float = 0
    pinged: float = 0
    node: str | None = None
    result: Any = NotGiven
    backoff: float = 0
    computed: float = 0
    reason: str = ""

    runner: JobRunner
    subpath: tuple

    def __init__(self, runner: JobRunner, subpath: tuple) -> None:
        self.runner = runner
        self.subpath = subpath

    def _dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in self.ATTRS:
            v = getattr(self, k, NotGiven)
            if v is NotGiven:
                continue
            out[k] = v
        return out

    def _load(self, value: Mapping[str, Any] | None) -> None:
        if value is None:
            for k in self.ATTRS:
                with suppress(AttributeError):
                    delattr(self, k)
            return
        for k in self.ATTRS:
            if k in value:
                setattr(self, k, value[k])

    @property
    def path(self) -> Path:
        """Full link path of this state entry."""
        return self.runner.statepath + Path.build(self.subpath)

    async def save(self) -> None:
        """Push the current state to the link.

        State messages are retained so that the runner can query the
        last-known status of jobs even though they live below the
        non-retained ``run.*`` prefix by default.
        """
        await self.runner.link.d_set(self.path, self._dump(), retain=True)

    async def delete(self) -> None:
        """Remove this entry from the link."""
        with suppress(KeyError):
            await self.runner.link.d.delete(self.path)


class JobEntry:
    """One job entry.

    The entry mirrors a record stored under the configured ``prefix``.
    The runner instantiates one such entry per known job.

    Attributes correspond to the same-named fields stored in the
    ``code data delay ok_after repeat backoff target info`` mapping.
    """

    ATTRS: ClassVar[tuple[str, ...]] = (
        "code",
        "data",
        "delay",
        "ok_after",
        "repeat",
        "backoff",
        "target",
        "info",
    )

    delay: float = 100
    repeat: float = 0
    target: float | None = 0
    backoff: float = 1.1
    ok_after: float = 0
    code: Path | None = None
    data: dict[str, Any]
    info: str = ""

    runner: JobRunner
    subpath: tuple
    state: StateEntry

    scope: anyio.CancelScope | None = None
    retry: float | None = None
    _comment: str | None = None
    _q: Any = None
    _running: bool = False
    _logger: logging.Logger

    def __init__(self, runner: JobRunner, subpath: tuple) -> None:
        self.runner = runner
        self.subpath = subpath
        self.data = {}
        self.state = StateEntry(runner, subpath)
        self._logger = logger_for(Path.build(subpath))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.subpath!r}:{self.code!r}>"

    @property
    def path(self) -> Path:
        """Full link path of this job entry."""
        return self.runner.path + Path.build(self.subpath)

    def update_value(self, value: Mapping[str, Any] | None) -> None:
        """Apply a freshly-arrived data update to the job's attributes.

        If the code attribute changes while the job is running, the
        running task is cancelled.  Likewise if the target is cleared.
        """
        old_code = self.code
        if value is None:
            for k in self.ATTRS:
                with suppress(AttributeError):
                    delattr(self, k)
        else:
            for k in self.ATTRS:
                if k in value:
                    setattr(self, k, value[k])
            if "data" not in value:
                self.data = {}

        if self.scope is not None:
            if value is None or self.code != old_code:
                self._comment = "Cancel: Code changed"
                self.scope.cancel()
            elif not self.target:
                self._comment = "Cancel: target zeroed"
                self.scope.cancel()

    def should_start(self) -> tuple[float | bool | None, str]:
        """Return when, if ever, this job should be started next.

        Returns:
            ``(False, reason)`` when no start is desired,
            ``(None, reason)`` when this node should ignore the job,
            ``(timestamp, reason)`` otherwise (``0`` means "right now").
        """
        st = self.state
        if self.code is None:
            return False, "no code"
        if st.node is not None:
            return None, "node set"
        if st.started and not st.stopped:
            raise RuntimeError("Running! should not be called")
        if self.target is None:
            return False, "no target"
        if self.target > st.started:
            return self.target, "target > started"
        if st.backoff:
            return st.stopped + self.delay * (self.backoff**st.backoff), "backoff"
        if self.repeat:
            return st.stopped + self.repeat, "repeat"
        if st.started and st.started > st.stopped:
            return False, "is started"
        return 0, "no target"

    async def send_event(self, evt: Any) -> None:
        """Forward an event to the running task's queue, if any."""
        if self._q is None:
            if self._running:
                self._logger.info("Discarding %r", evt)
            return
        if self._q.qsize() < QLEN - 1:
            self._logger.debug("Event: %r", evt)
            await self._q.put(evt)
        elif self._q.qsize() == QLEN - 1:
            self._logger.warning("Queue full")
            await self._q.put(None)
            self._q = None
            self._logger.info("Discarding %r", evt)

    async def run(self) -> None:
        """Execute the configured code once.

        Updates :attr:`state` accordingly and reports errors through the
        link's error channel.
        """
        if self.code is None:
            return

        st = self.state
        link = self.runner.link
        t = time.time()
        try:
            self._running = True
            try:
                self._logger.debug("Start")
                if st.node is not None:
                    raise RuntimeError(f"already running on {st.node}")
                code = link.code_at(self.code)
                code_obj = await code
                payload = self.data or {}
                default = {}
                if isinstance(code_obj._data, dict):  # noqa: SLF001
                    default = code_obj._data.get("default", {}) or {}  # noqa: SLF001
                kw = combine_dict(payload, default, deep=True)
                self._q = create_queue(QLEN)
                admin = CallAdmin(self, kw)
                kw["_self"] = admin
                kw["_link"] = link
                kw["_cfg"] = link.cfg
                kw["_cls"] = _CLASSES
                kw["_info"] = self._q
                kw["_P"] = P
                kw["_Path"] = Path
                kw["_log"] = self._logger
                kw["_digits"] = digits

                st.started = t
                st.node = self.runner.name
                await st.save()

                res = await admin._run(code_obj, kw)  # noqa: SLF001
            except BaseException as exc:
                self._logger.info("Error: %r", exc)
                raise
            else:
                self._logger.debug("End")
            finally:
                self.scope = None
                self._q = None
                t = time.time()

        except ErrorRecorded:
            self._comment = None
            st.backoff = min(st.backoff + 1, 20)
        except Exception as exc:
            c, self._comment = self._comment, None
            with anyio.move_on_after(5, shield=True):
                await link.e_exc(self.path, exc, data=self.data, comment=c)
            st.backoff = min(st.backoff + 1, 20)
        else:
            st.result = res
            st.backoff = 0
            await link.e_ok(self.path)
        finally:
            with anyio.fail_after(2, shield=True):
                if st.node == self.runner.name:
                    st.node = None
                self._running = False
                st.stopped = t
                if st.backoff > 0:
                    self.retry = t + (self.backoff**st.backoff) * self.delay
                else:
                    self.retry = None
                with suppress(anyio.ClosedResourceError):
                    await st.save()
                await self.runner.trigger_rescan()


class CallAdmin:
    """Helpers exposed to running code as the ``_self`` keyword.

    Instances are short-lived: one per execution of a job.
    """

    _taskgroup: TaskGroup | None = None
    _stack: AsyncExitStack | None = None
    _restart: bool = False
    _n_watch: int = 0
    _n_watch_seen: int = 0

    _entry: JobEntry
    _link: LinkSender
    _data: dict[str, Any]

    def __init__(self, entry: JobEntry, data: dict[str, Any]) -> None:
        self._entry = entry
        self._link = entry.runner.link
        self._data = data
        self._logger = entry._logger  # noqa: SLF001

    async def _run(self, code: Any, data: dict[str, Any]) -> Any:
        while True:
            self._n_watch = 0
            self._n_watch_seen = 0
            res = await self._run2(code, data)
            if self._restart:
                self._restart = False
                continue
            return res

    async def _run2(self, code: Any, data: dict[str, Any]) -> Any:
        self._logger.debug("Start %s with %s", self._entry.path, self._entry.code)
        async with anyio.create_task_group() as tg, AsyncExitStack() as stack:
            self._stack = stack
            self._taskgroup = tg
            self._entry.scope = sc = tg.cancel_scope

            data["_self"] = self

            oka = getattr(self._entry, "ok_after", 0) or 0
            if oka > 0:

                async def _ok_after(t: float) -> None:
                    await anyio.sleep(t)
                    await self.setup_done()

                tg.start_soon(_ok_after, oka)

            await self._entry.send_event(ReadyMsg(0))
            res = await code(**data)
            sc.cancel()
            return res

    def cancel(self) -> None:
        """Cancel the running task."""
        if self._taskgroup is not None:
            self._taskgroup.cancel_scope.cancel()

    async def spawn(
        self,
        proc: Callable[..., Awaitable[Any]],
        *a: Any,
        **kw: Any,
    ) -> anyio.CancelScope:
        """Start a background subtask.

        The task is auto-cancelled when the surrounding job ends.
        """
        if self._taskgroup is None:
            raise RuntimeError("not running")
        return await spawn(self._taskgroup, proc, *a, **kw)

    async def setup_done(self, **kw: Any) -> None:
        """Declare that the job has finished its startup phase.

        Clears any back-off and posts an ``ok`` to the link's error
        channel.
        """
        self._entry.state.backoff = 0
        await self._entry.state.save()
        await self._link.e_ok(self._entry.path, **kw)

    async def error(self, path: Path | None = None, **kw: Any) -> None:
        """Record an error against ``path`` and raise :class:`ErrorRecorded`.

        See :meth:`moat.link.client.LinkSender.e_exc` for keyword
        details.  ``path`` defaults to the running job's path.
        """
        if path is None:
            path = self._entry.path
        exc = kw.pop("exc", None)
        if exc is None:
            await self._link.e_info(path, kw.pop("message", "error"), **kw)
        else:
            await self._link.e_exc(path, exc, **kw)
        raise ErrorRecorded

    async def open_context(self, ctx: Any) -> Any:
        """Enter an async context manager whose lifetime is bound to the job."""
        if self._stack is None:
            raise RuntimeError("not running")
        return await self._stack.enter_async_context(ctx)

    async def watch(self, path: Path, cls: type[ChangeMsg] = ChangeMsg, **kw: Any) -> _Watcher:
        """Watch ``path`` for changes.

        Updates are dispatched to the job's event queue as instances of
        ``cls`` (a :class:`ChangeMsg` subclass).  When ``fetch`` (the
        default) is set, a :class:`ReadyMsg` is emitted once all
        watchers have transmitted their initial state.

        Pass ``subtree=True`` to also receive changes for children of
        ``path``.
        """
        if isinstance(path, (tuple, list)):
            path = Path.build(path)
        elif not isinstance(path, Path):
            raise TypeError(f"You didn't pass in a path: {path!r}")

        if kw.setdefault("fetch", True):
            self._n_watch += 1

        w = _Watcher(self, cls, path, kw)
        if self._taskgroup is None:
            raise RuntimeError("not running")
        self._taskgroup.start_soon(w.run)
        return w

    async def monitor(self, path: Path, cls: type[MQTTmsg] = MQTTmsg, **kw: Any) -> _Monitor:
        """Subscribe to MQTT topic ``path``.

        Each message is dispatched to the job's event queue as an
        instance of ``cls`` (a :class:`MQTTmsg` subclass).  MQTT
        wildcards are supported.
        """
        if isinstance(path, (tuple, list)):
            path = Path.build(path)
        elif not isinstance(path, Path):
            raise TypeError(f"You didn't pass in a path: {path!r}")

        m = _Monitor(self, cls, path, kw)
        if self._taskgroup is None:
            raise RuntimeError("not running")
        self._taskgroup.start_soon(m.run)
        return m

    async def send(self, path: Path, value: Any = NotGiven) -> None:
        """Publish ``value`` to MQTT topic ``path``."""
        if isinstance(path, (tuple, list)):
            path = Path.build(path)
        elif not isinstance(path, Path):
            raise TypeError(f"You didn't pass in a path: {path!r}")
        await self._link.send(path, value, retain=False)

    async def set(self, path: Path, value: Any) -> Any:
        """Store ``value`` at link path ``path``."""
        if isinstance(path, (tuple, list)):
            path = Path.build(path)
        elif not isinstance(path, Path):
            raise TypeError(f"You didn't pass in a path: {path!r}")
        return await self._link.d_set(path, value)

    async def get(self, path: Path) -> Any:
        """Fetch the value stored at link path ``path``."""
        if isinstance(path, (tuple, list)):
            path = Path.build(path)
        elif not isinstance(path, Path):
            raise TypeError(f"You didn't pass in a path: {path!r}")
        return await self._link.d_get(path)

    async def timer(self, delay: float, cls: type[TimerMsg] = TimerMsg) -> _Timer:
        """Schedule a one-shot timer.

        After ``delay`` seconds a ``cls`` (:class:`TimerMsg` subclass)
        instance is queued to the job's event queue.
        """
        if self._taskgroup is None:
            raise RuntimeError("not running")
        t = _Timer(self._entry, cls, self._taskgroup)
        await t.run(delay)
        return t


class _Watcher:
    """Background task: watch a link path on behalf of a running job."""

    admin: CallAdmin
    client: LinkSender
    path: Path
    kw: dict[str, Any]
    cls: type[ChangeMsg]
    scope: anyio.CancelScope | None

    def __init__(
        self,
        admin: CallAdmin,
        cls: type[ChangeMsg],
        path: Path,
        kw: dict[str, Any],
    ) -> None:
        self.admin = admin
        self.client = admin._link  # noqa: SLF001
        self.path = path
        self.kw = kw
        self.cls = cls
        self.scope = None

    async def run(self) -> None:
        kw = dict(self.kw)
        fetch = bool(kw.pop("fetch", True))
        subtree = bool(kw.pop("subtree", False))
        # ``state=None``: initial value + updates; ``state=False``: updates only.
        state: bool | None = None if fetch else False
        with anyio.CancelScope() as sc:
            self.scope = sc
            async with self.client.d_watch(
                self.path,
                state=state,
                subtree=subtree,
                mark=fetch,
                meta=False,
            ) as mon:
                async for item in mon:
                    if item is None:
                        if fetch:
                            self.admin._n_watch_seen += 1  # noqa: SLF001
                            if (
                                self.admin._n_watch_seen  # noqa: SLF001
                                >= self.admin._n_watch  # noqa: SLF001
                            ):
                                await self.admin._entry.send_event(  # noqa: SLF001
                                    ReadyMsg(self.admin._n_watch_seen),  # noqa: SLF001
                                )
                        continue
                    if subtree:
                        p, d = item
                        full = self.path + p
                    else:
                        d = item
                        full = self.path
                    chg = self.cls(d)
                    chg.value = d
                    chg.path = full
                    await self.admin._entry.send_event(chg)  # noqa: SLF001

    def cancel(self) -> bool:
        """Stop the watcher."""
        if self.scope is None:
            return False
        sc, self.scope = self.scope, None
        sc.cancel()
        return True


class _Monitor:
    """Background task: subscribe to MQTT on behalf of a running job."""

    admin: CallAdmin
    client: LinkSender
    path: Path
    kw: dict[str, Any]
    cls: type[MQTTmsg]
    scope: anyio.CancelScope | None

    def __init__(
        self,
        admin: CallAdmin,
        cls: type[MQTTmsg],
        path: Path,
        kw: dict[str, Any],
    ) -> None:
        self.admin = admin
        self.client = admin._link  # noqa: SLF001
        self.path = path
        self.kw = kw
        self.cls = cls
        self.scope = None

    async def run(self) -> None:
        with anyio.CancelScope() as sc:
            self.scope = sc
            async with self.client.monitor(self.path, **self.kw) as mon:
                async for msg in mon:
                    chg = self.cls(getattr(msg, "raw", None))
                    with suppress(AttributeError):
                        chg.value = msg.data
                    chg.path = Path.build(msg.topic)
                    await self.admin._entry.send_event(chg)  # noqa: SLF001

    def cancel(self) -> bool:
        """Stop the monitor."""
        if self.scope is None:
            return False
        sc, self.scope = self.scope, None
        sc.cancel()
        return True


class _Timer:
    """Background task: schedule a one-shot timer."""

    entry: JobEntry
    cls: type[TimerMsg]
    scope: anyio.CancelScope | None
    delay: float

    def __init__(self, entry: JobEntry, cls: type[TimerMsg], tg: TaskGroup) -> None:
        self.entry = entry
        self.cls = cls
        self.scope = None
        self._taskgroup = tg
        self.delay = 0

    async def _run(self) -> None:
        with anyio.CancelScope() as sc:
            self.scope = sc
            await anyio.sleep(self.delay)
            self.scope = None
            await self.entry.send_event(self.cls(self))

    def cancel(self) -> bool:
        """Cancel a pending timer."""
        if self.scope is None:
            return False
        sc, self.scope = self.scope, None
        sc.cancel()
        return True

    async def run(self, delay: float) -> None:
        """Restart the timer with a new ``delay``."""
        self.cancel()
        self.delay = delay
        if self.delay > 0:
            self._taskgroup.start_soon(self._run)


class JobRunner:
    """Background job runner.

    Args:
        link: a connected MoaT-Link client.
        cfg: the ``job`` configuration block (already merged with
            defaults).
        subpath: extra path components placed below
            ``cfg.prefix + cfg.sub[SUB]``.
        nodes: cluster size hint (used by :class:`AnyJobRunner`).
    """

    SUB: ClassVar[str]
    "Sub-key inside ``cfg.sub`` selecting the path layout for this mode."

    link: LinkSender
    cfg: attrdict
    nodes: int
    path: Path
    statepath: Path
    subpath: Path

    entries: dict[tuple, JobEntry]
    _trigger: anyio.Event
    _start_delay: float
    _tagged: bool = True
    _act: Any = None
    _run_now_task: anyio.CancelScope | None = None
    _tg: TaskGroup
    node_history: NodeList
    _ready: bool = False

    def __init__(
        self,
        link: LinkSender,
        cfg: attrdict,
        subpath: Path,
        nodes: int = 0,
    ) -> None:
        self.link = link
        self.cfg = cfg
        self.nodes = nodes
        self.subpath = subpath
        self.path = Path.build(cfg["prefix"]) + subpath
        self.statepath = Path.build(cfg["state"]) + subpath
        self.entries = {}
        self._trigger = anyio.Event()
        self._start_delay = cfg["start_delay"]
        self.node_history = NodeList(0)

    @property
    def name(self) -> str:
        """Our node name (the link's name)."""
        return self.link.name

    @property
    def group(self) -> Path:
        """The actor topic used for cluster coordination."""
        return (P("run.job") | self.cfg["name"] | self.SUB) + self.subpath

    def _get(self, subpath: tuple) -> JobEntry:
        try:
            return self.entries[subpath]
        except KeyError:
            self.entries[subpath] = e = JobEntry(self, subpath)
            return e

    async def trigger_rescan(self) -> None:
        """Wake the scheduler so it re-evaluates which jobs to start."""
        if self._trigger is not None:
            self._trigger.set()

    @asynccontextmanager
    async def run(self) -> AsyncIterator[JobRunner]:
        """Async context manager.

        Loads initial data, then keeps watching for updates and runs
        eligible jobs.  Yields ``self``.
        """
        async with anyio.create_task_group() as tg:
            self._tg = tg
            await tg.start(self._watch_jobs)
            await tg.start(self._watch_state)
            tg.start_soon(self._run_actor)
            self._ready = True
            try:
                yield self
            finally:
                tg.cancel_scope.cancel()

    async def _watch_jobs(self, *, task_status: Any) -> None:
        """Maintain the in-memory job tree from the link."""
        async with self.link.d_watch(
            self.path,
            state=None,
            subtree=True,
            mark=True,
            meta=False,
        ) as mon:
            async for item in mon:
                if item is None:
                    task_status.started()
                    continue
                p, d = item
                key = _split_subpath(p)
                if d is NotGiven or d is None:
                    e = self.entries.pop(key, None)
                    if e is not None and e.scope is not None:
                        e._comment = "Cancel: entry removed"  # noqa: SLF001
                        e.scope.cancel()
                    continue
                e = self._get(key)
                e.update_value(d)
                await self.trigger_rescan()

    async def _watch_state(self, *, task_status: Any) -> None:
        """Maintain the in-memory state tree from the link.

        Also enforces ownership: if a running job's state record is
        deleted, or its ``node`` field no longer points at this runner,
        the running task is cancelled immediately.
        """
        async with self.link.d_watch(
            self.statepath,
            state=None,
            subtree=True,
            mark=True,
            meta=False,
        ) as mon:
            async for item in mon:
                if item is None:
                    task_status.started()
                    continue
                p, d = item
                key = _split_subpath(p)
                e = self._get(key)
                if d is NotGiven or d is None or not isinstance(d, dict):
                    e.state._load(None)  # noqa: SLF001
                else:
                    e.state._load(d)  # noqa: SLF001

                # Cancel a locally-running job whenever its state was
                # taken away (deleted, or node cleared / reassigned).
                if e.scope is not None and e._running and e.state.node != self.name:  # noqa: SLF001
                    e._comment = f"Cancel: state.node={e.state.node!r}"  # noqa: SLF001
                    e.scope.cancel()

                await self.trigger_rescan()

    async def _run_now(self, evt: anyio.Event | None = None) -> None:
        """Inner scheduler loop.

        Periodically inspects all known jobs and starts those whose
        target time has arrived.
        """
        with anyio.CancelScope() as sc:
            self._run_now_task = sc
            if evt is not None:
                evt.set()
            t = time.time()
            t_next = t
            while True:
                if t_next > t:
                    with anyio.move_on_after(t_next - t):
                        await self._trigger.wait()
                        self._trigger = anyio.Event()
                t = time.time()
                t_next = t + 999
                for j in list(self.entries.values()):
                    if j._running or j.scope is not None:  # noqa: SLF001
                        continue
                    d, r = j.should_start()
                    if d is None:
                        continue
                    if d is False or (isinstance(d, (int, float)) and d > t):
                        j.state.computed = float(d) if isinstance(d, (int, float)) else 0
                        j.state.reason = r
                        if self._tagged:
                            with suppress(anyio.ClosedResourceError):
                                await j.state.save()
                        if isinstance(d, (int, float)) and d and t_next > d:
                            t_next = d
                        continue
                    self._tg.start_soon(j.run)
                    await anyio.sleep(self._start_delay)

    async def _run_actor(self) -> None:
        """Override: drive an asyncactor to coordinate with the cluster."""
        raise RuntimeError("override me")

    async def _notify_actor_state(self, msg: Any = None) -> None:
        """Notify all running jobs of the current actor state."""
        ac_n = len(self.node_history)
        if ac_n == 0 or msg is None:
            cls = BrokenState
        elif self.name in self.node_history and ac_n == 1:
            cls = DetachedState
        elif self._act is not None and ac_n >= self.nodes:
            cls = CompleteState
        else:
            cls = PartialState
        st = cls(msg)
        for j in list(self.entries.values()):
            await j.send_event(st)


class AnyJobRunner(JobRunner):
    """Run jobs on exactly one of any cluster members.

    Uses an actor for cluster coordination; whichever node is currently
    "tagged" picks new jobs to run.
    """

    SUB: ClassVar[str] = "group"
    _tagged: bool = False

    async def _run_actor(self) -> None:
        import psutil  # noqa: PLC0415

        async with LinkActor(
            self.link,
            self.name,
            topic=self.group,
            cfg=self.cfg["actor"],
        ) as act:
            self._act = act
            psutil.cpu_percent(interval=None)
            await act.set_value(0)

            async for msg in act:
                if isinstance(msg, PingEvent):
                    await act.set_value(100 - psutil.cpu_percent(interval=None))
                    self.node_history += msg.node
                elif isinstance(msg, TagEvent):
                    self._tagged = True
                    await act.set_value(100 - psutil.cpu_percent(interval=None))
                    self.node_history += self.name
                    evt = anyio.Event()
                    self._tg.start_soon(self._run_now, evt)
                    await evt.wait()
                elif isinstance(msg, UntagEvent):
                    self._tagged = False
                    await act.set_value(100 - psutil.cpu_percent(interval=None))
                    if self._run_now_task is not None:
                        self._run_now_task.cancel()
                await self._notify_actor_state(msg)


class SingleJobRunner(JobRunner):
    """Run jobs on one specific node, named by the second-to-last subpath element."""

    SUB: ClassVar[str] = "single"

    async def _run_actor(self) -> None:
        async with LinkActor(
            self.link,
            self.name,
            topic=self.group,
            cfg=self.cfg["actor"],
        ) as act:
            self._act = act
            await act.set_value(0)
            self._tg.start_soon(self._run_now)
            async for msg in act:
                if isinstance(msg, AuthPingEvent):
                    self.node_history += msg.node
                    await self._notify_actor_state(msg)


class AllJobRunner(SingleJobRunner):
    """Run jobs on every node.

    Each node maintains its own state subtree below
    ``<state>/<sub.all>/<group>/<node>``.
    """

    SUB: ClassVar[str] = "all"

    def __init__(
        self,
        link: LinkSender,
        cfg: attrdict,
        subpath: Path,
        nodes: int = 0,
    ) -> None:
        super().__init__(link, cfg, subpath, nodes)
        self.statepath = self.statepath + Path.build((link.name,))


class _DebugStub:
    """Minimal :class:`JobRunner` look-alike used by :func:`debug_run`.

    Only the attributes :class:`JobEntry` and :class:`StateEntry`
    actually touch are provided.
    """

    def __init__(self, link: LinkSender, path: Path, statepath: Path) -> None:
        self.link = link
        self.path = path
        self.statepath = statepath
        self.name = link.id

    async def trigger_rescan(self) -> None:
        """No-op: there is no scheduler to wake."""


async def debug_run(
    link: LinkSender,
    job_path: Path,
    state_path: Path,
    data_overrides: Mapping[str, Any] | None = None,
    *,
    use_pdb: bool = False,
    force: bool = False,
    log_stream: Any = None,
) -> Any:
    """Run a single job interactively once.

    The current process takes ownership of the job: ``state.node`` is
    set to ``link.id`` and the snippet is invoked directly.  No actor
    coordination, no rescheduling, no retry on failure.

    Args:
        link: Connected MoaT-Link client.
        job_path: Full link path of the stored job record.
        state_path: Full link path of the matching state record.
        data_overrides: Extra values merged on top of the job's
            stored ``data`` dictionary.  Keys present here win.
        use_pdb: If true, drop into :mod:`pdb` immediately before the
            snippet is called.
        force: Run even when ``state.node`` is set to a different
            owner.  Without this flag a `RuntimeError` is raised
            instead of stealing the job.
        log_stream: If not `None`, a stream handler at level
            ``DEBUG`` is attached to the snippet's ``_log`` logger and
            output is mirrored there for the duration of the call.

    Returns:
        Whatever the snippet returned, or `None` on error.
    """
    try:
        job = await link.d_get(job_path)
    except KeyError as exc:
        raise RuntimeError(f"No job at {job_path}") from exc
    if not isinstance(job, Mapping) or "code" not in job:
        raise RuntimeError(f"Job at {job_path} has no 'code'")

    try:
        prev = await link.d_get(state_path)
    except KeyError:
        prev = None

    our_id = link.id
    if (
        not force
        and isinstance(prev, Mapping)
        and prev.get("node")
        and prev.get("node") != our_id
        and prev.get("started", 0) > prev.get("stopped", 0)
    ):
        owner = prev["node"]
        if await link.is_client_alive(owner):
            raise RuntimeError(
                f"Job already running on {owner!r} (use force=True / -f to override)",
            )

    stub = _DebugStub(link, job_path, state_path)
    entry = JobEntry(stub, ())  # ty:ignore[invalid-argument-type]  # subpath empty: path == stub.path
    entry.update_value(dict(job))
    # The snippet's ``_log`` logger should reflect the job path, not
    # the empty subpath we used to wire :attr:`JobEntry.path`.
    entry._logger = logger_for(job_path)  # noqa: SLF001
    if isinstance(prev, Mapping):
        entry.state._load(dict(prev))  # noqa: SLF001

    if data_overrides:
        entry.data = combine_dict(dict(data_overrides), entry.data or {}, deep=True)

    handler: logging.Handler | None = None
    if log_stream is not None:
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s"),
        )
        entry._logger.addHandler(handler)  # noqa: SLF001
        if entry._logger.level == logging.NOTSET or entry._logger.level > logging.DEBUG:  # noqa: SLF001
            entry._logger.setLevel(logging.DEBUG)  # noqa: SLF001

    # Take ownership.  Clear any leftover "running" markers.
    entry.state.started = 0
    entry.state.stopped = 0
    entry.state.node = our_id
    entry.state.backoff = 0
    await entry.state.save()

    st = entry.state
    t = time.time()
    result: Any = None
    try:
        entry._running = True  # noqa: SLF001
        if entry.code is None:
            raise RuntimeError(f"Job at {job_path} has no 'code'")
        code = link.code_at(entry.code)
        code_obj = await code
        payload = entry.data or {}
        default = {}
        if isinstance(code_obj._data, dict):  # noqa: SLF001
            default = code_obj._data.get("default", {}) or {}  # noqa: SLF001
        kw = combine_dict(payload, default, deep=True)
        entry._q = create_queue(QLEN)  # noqa: SLF001
        admin = CallAdmin(entry, kw)
        kw["_self"] = admin
        kw["_link"] = link
        kw["_cfg"] = link.cfg
        kw["_cls"] = _CLASSES
        kw["_info"] = entry._q  # noqa: SLF001
        kw["_P"] = P
        kw["_Path"] = Path
        kw["_log"] = entry._logger  # noqa: SLF001
        kw["_digits"] = digits

        st.started = t
        await st.save()

        if use_pdb:
            import pdb  # noqa: PLC0415, T100

            pdb.set_trace()  # noqa: T100
        result = await admin._run(code_obj, kw)  # noqa: SLF001
    except ErrorRecorded:
        pass
    except Exception as exc:
        with anyio.move_on_after(5, shield=True):
            await link.e_exc(job_path, exc, data=entry.data)
        raise
    else:
        st.result = result
        await link.e_ok(job_path)
    finally:
        entry._running = False  # noqa: SLF001
        entry._q = None  # noqa: SLF001
        with anyio.fail_after(2, shield=True):
            if st.node == our_id:
                st.node = None
            st.stopped = time.time()
            with suppress(anyio.ClosedResourceError):
                await st.save()
        if handler is not None:
            entry._logger.removeHandler(handler)  # noqa: SLF001

    return result
