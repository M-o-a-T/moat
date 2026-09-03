"""
Notification package
"""

from __future__ import annotations

import anyio
import logging
import time
from abc import ABCMeta, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager

from moat.util import CtxObj, NotGiven, as_service, attrdict
from moat.lib.path import P, Path
from moat.lib.priomap import PrioMap

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import Link
    from moat.link.node import Node

    from collections.abc import AsyncIterator
    from typing import Any, Self

__all__ = ["ErrorMirror", "Notifier", "Notify", "get_backend"]

logger = logging.getLogger(__name__)

#: Severity levels recognised by the mirror.
#: Higher numbers mean more severe.
_SEVERITY: dict[str, int] = {
    "debug": 1,
    "info": 2,
    "warning": 3,
    "error": 4,
    "fatal": 5,
}


class ErrorMirror:
    """Mirror error entries to the notification subtree.

    Watches ``error.*`` and, for each entry, collects mirroring rules from a
    dynamic ``notify_vecs`` subtree (stored below ``conv.*`` in the link data
    tree, analogous to the ``codec_vecs`` mechanism used by the Venus gateway).
    Rules are looked up with :meth:`~moat.link.node.Node.collect`, which merges data from all
    matching wildcard branches — more specific branches override less
    specific ones.

    A rule dict may contain:

    - ``min_level`` — minimum severity to mirror (default ``"warning"``).
    - ``skip`` — set to ``True`` to suppress mirroring for this branch.
    - ``prio`` — override the notification priority.
    - ``title`` — override the notification title.

    When an error is cleared (``ok=True`` or deleted) the corresponding
    notification is removed.
    """

    link: Link
    cfg: attrdict
    notify_vecs: Node | None

    def __init__(self, cfg: attrdict):
        """Set up the mirror.

        Args:
            cfg: The ``link.notify`` sub-configuration.  Relevant keys
                 are documented in ``_cfg.yaml``.
        """
        self.cfg = cfg
        self.notify_vecs = None

    async def run(self, link: Link, evt: anyio.Event | None = None) -> None:
        """Run the mirror task.

        Args:
            link: A connected link client.
            evt: Optional readiness event.
        """
        self.link = link
        notify_path = self.cfg.get("path", P("notify"))

        # Fetch the notify-vecs tree, if configured.
        # This mirrors the codec_vecs pattern in moat/link/gate/venus.py.
        vecs_path = self.cfg.get("vecs", None)
        if isinstance(vecs_path, Path):
            async with link.d_watch(
                P("conv") + vecs_path, subtree=True, state=None, meta=False
            ) as cdv:
                self.notify_vecs = await cdv.get_node()
            await self._run_loop(link, notify_path, evt)
        else:
            # No vecs tree configured — mirror everything at warning+.
            await self._run_loop(link, notify_path, evt)

    async def _run_loop(self, link: Link, notify_path: Path, evt: anyio.Event | None) -> None:
        """Watch the error subtree and mirror qualifying entries."""
        async with link.d_watch(P("error"), subtree=True, state=None, meta=True) as mon:
            if evt is not None:
                evt.set()

            async for path, data, _meta in mon:
                # The watcher is rooted at 'error', so 'path' is already
                # the original path without the 'error' prefix.
                orig = path

                if data is NotGiven:
                    # Error entry deleted → clear notification.
                    await link.d_set(notify_path + orig, NotGiven)
                    continue

                if isinstance(data, dict) and data.get("ok", False):
                    # Error resolved → clear notification.
                    await link.d_set(notify_path + orig, NotGiven)
                    continue

                # Collect mirroring rules from the notify_vecs tree.
                # Node.collect merges data from all matching branches,
                # with more specific matches overriding less specific ones.
                rule: attrdict = attrdict()
                if self.notify_vecs is not None:
                    try:
                        rule = self.notify_vecs.collect(orig)
                    except (KeyError, ValueError):
                        rule = attrdict()

                # Check if this branch should be skipped.
                if rule.get("skip", False):
                    continue

                # Determine severity.
                level = data.get("level", 3) if isinstance(data, dict) else 3
                if isinstance(level, str):
                    sev = _SEVERITY.get(level, 3)
                else:
                    sev = int(level)

                # Check severity threshold from the collected rule.
                min_level = rule.get("min_level", "warning")
                min_severity = (
                    _SEVERITY.get(min_level, 3) if isinstance(min_level, str) else int(min_level)
                )
                if sev < min_severity:
                    continue

                # Build the notification message.
                msg: dict[str, Any] = {}
                if isinstance(data, dict):
                    msg_text = data.get("msg", "")
                    exc = data.get("exc", "")
                    bt = data.get("bt", "")
                    msg["msg"] = str(msg_text or exc)
                    if bt:
                        msg["bt"] = bt
                    # Priority: rule override > severity mapping.
                    prio = rule.get("prio", None)
                    if prio is None:
                        prio = self._severity_to_prio(sev)
                    if prio is not None:
                        msg["prio"] = prio
                    # Title: rule override > original path.
                    title = rule.get("title", None)
                    msg["title"] = str(title) if title is not None else str(orig)
                    # Carry over auxiliary data.
                    for key in ("data", "aux", "n", "first"):
                        if key in data:
                            msg[key] = data[key]
                else:
                    msg["msg"] = str(data)
                    msg["title"] = str(orig)

                await link.d_set(notify_path + orig, msg)

    @staticmethod
    def _severity_to_prio(sev: int) -> str | None:
        """Map a numeric severity to a notification priority string.

        Args:
            sev: Severity level (1–5).

        Returns:
            Priority name understood by the ntfy backend, or ``None``.
        """
        if sev >= 5:
            return "fatal"
        if sev >= 4:
            return "error"
        if sev >= 3:
            return "warning"
        if sev >= 2:
            return "info"
        return "debug"


class Notify:
    """
    Notification runner.
    """

    link: Link

    def __init__(self, cfg):
        self.cfg = cfg
        self.dropped: PrioMap[Notifier, float] = PrioMap()

    async def run(self, link: Link, evt: anyio.Event | None = None):
        """
        Task that reads notifications from MoaT-Link and posts them.
        """
        self.link = link
        async with AsyncExitStack() as ex:
            backend = self.cfg.backend
            if isinstance(backend, str):
                backend = (backend,)

            self._backends = {}
            for name in backend:
                cfg = self.cfg.get(name, attrdict())
                try:
                    notifier = await ex.enter_async_context(get_backend(name, link, cfg))
                except Exception as exc:
                    logger.warning("Backend %r", name, exc_info=exc)
                else:
                    self._backends[name] = notifier

            if not self._backends:
                raise RuntimeError("No backend worked.")

            try:
                await self._run(evt)
            finally:
                with anyio.move_on_after(2, shield=True):
                    await self.send(
                        topic="error.notify",
                        title="Backend stopped",
                        msg="The backend terminated.",
                        prio="fatal",
                    )

    async def send(self, **kw) -> None:
        """Send this notification to that topic."""
        # reactivate dropped items
        tm = time.monotonic()
        retry: set[Notifier] = set()
        error_seen = False

        # Collect failed backends for retrying
        while self.dropped:
            b_e, t = self.dropped.peek()
            if t > tm:
                break
            del self.dropped[b_e]
            retry.add(b_e)

        for name, b_e in list(self._backends.items()):
            if b_e in self.dropped:
                continue
            try:
                await b_e.send(**kw)
            except Exception as exc:
                # Log failed backends only once
                if b_e in self.dropped:
                    continue
                error_seen = True

                self.dropped[b_e] = tm + self.cfg.timeout.retry
                await self.link.e_exc(
                    P("run.notify.backend") / name,
                    exc,
                    msg=f"The notification backend {name} failed.",
                    val=kw,
                    level=3,
                )
            else:
                if b_e in retry:
                    # No lock because this can only happen in one branch
                    await self.link.e_ok(P("run.notify.backend") / name)

        if len(self.dropped) >= len(self._backends):
            # This might conceivably happen in more than one branch
            # if more than one backend fails at a time, but we don't care
            if error_seen:
                await self.link.e_info(
                    P("run.notify.backend"), "All notification backends failed.", level=4
                )
        elif any(x not in self.dropped for x in retry):
            await self.link.e_ok(P("run.notify.backend"))

    async def _run(self, evt) -> None:
        """
        A bridge that monitors the MoaT-Link notify subtree.
        """
        async with as_service(attrdict(debug=False)) as srv:
            try:
                await srv.tg.start(self._keepalive)

                async with self.link.d_watch(
                    self.cfg.path, subtree=True, meta=True, state=None
                ) as mon:
                    srv.set()
                    if evt is not None:
                        evt.set()
                    async for path, msg, meta in mon:
                        t = time.time()
                        if meta.timestamp < t - self.cfg.max_age:
                            continue
                        if msg is NotGiven:
                            # Treat as empty message, for now
                            msg = {"msg": "Deleted"}  # noqa:PLW2901
                        if isinstance(msg, dict):
                            if "title" not in msg:
                                msg["title"] = str(path)
                            await self.send(topic=path, **msg)
                        else:
                            await self.send(topic=path, title="?", msg=str(msg))

                    # not reached, loop doesn't terminate

            except Exception as exc:
                await self.send(
                    topic=P("error.notify"), msg=repr(exc), prio="error", title="Gateway failure"
                )
                raise

    async def _keepalive(self, *, task_status=anyio.TASK_STATUS_IGNORED) -> None:
        "Monitor the keepalive topic"
        bad = True
        link = self.link
        keep = self.cfg.keepalive
        ok_keep = keep.ok

        timeout = keep.get("timeout", link.cfg.timeout.ping.timeout)

        # The main host watcher publishes on the empty path
        async with link.d_watch(P("run.host"), state=None) as mon:
            task_status.started()
            mon = aiter(mon)  # noqa:PLW2901
            while True:
                if bad:
                    msg = await anext(mon)
                else:
                    try:
                        with anyio.fail_after(timeout):
                            msg = await anext(mon)
                    except TimeoutError:
                        msg = None

                if isinstance(msg, dict) and "id" in msg:
                    async with link.d_watch(P("run.ping.id") / msg["id"]) as mon2:
                        mon2 = aiter(mon2)  # noqa:PLW2901
                        while True:
                            try:
                                with anyio.fail_after(timeout):
                                    msg = await anext(mon2)
                                    if not msg.get("up", False):
                                        break
                                    if bad and "msg" in ok_keep:
                                        await self.send(topic="error.notify", **ok_keep)
                                        bad = False
                            except TimeoutError:
                                break

                await self.send(topic="error.notify", **keep)
                bad = True


def get_backend(name: str, link: Link, cfg: dict) -> Notifier:
    """
    Fetch the backend named in the config and initialize it.
    """
    from importlib import import_module  # noqa: PLC0415

    if "." not in name:
        name = "moat.link.notify." + name
    return import_module(name).Notifier(link, cfg)


class Notifier(CtxObj, metaclass=ABCMeta):
    "Base class for notification backends"

    def __init__(self, link: Link, cfg: attrdict):
        self.cfg = cfg
        self.link = link

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        yield self

    @abstractmethod
    async def send(
        self, topic: str | Path, title: str | None = None, msg: str | None = None, **kw
    ):
        """Send this notification to that topic."""
