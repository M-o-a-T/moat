"""
MoaT-Link services announce themselves with defined names.
"""

from __future__ import annotations

import anyio
import logging
import os
import platform
from anyio.abc import TaskStatus
from contextlib import asynccontextmanager
from warnings import warn

from attrs import define, field

from moat.util import NotGiven, P, Path, attrdict, ensure_cfg, gen_ident
from moat.util import as_service as _as_service

from .client import Link
from .exceptions import ServiceCleared, ServiceNotFound, ServiceSupplanted

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.base import MsgSender
    from moat.util.path import PathElem

    from .client import LinkSender

    from typing import Any

__all__ = ["announcing"]

logger = logging.getLogger(__name__)

# TODO when to warn vs. when to log a warning


class NoServiceWarning(UserWarning):
    """
    Warn when not running in a cgroup.
    """

    pass


async def get_service_path(host: Path | str | bool, name: Path | None = None):
    path: list[PathElem] = ["run", "host"]

    match host:
        case True:
            path.append(platform.node())
        case False:
            pass
        case Path():
            path.extend(list(host.raw))
        case str():
            path.append(host)
        case _:
            raise TypeError("Host must be bool/path/str, not {host !r}.")

    if name is not None:
        path.extend(name.raw)
        return Path.build(path)

    if (fake := os.environ.get("MT_SERVICE", None)) is not None:
        path.extend(P(fake))
        return Path.build(path)

    if int(os.environ.get("SYSTEMD_EXEC_PID", "0")) == os.getpid():
        async with await anyio.Path("/proc/self/cgroup").open("r") as cgf:
            async for cg in cgf:
                logger.info("Control Group: %s", cg)
                for cge in cg.strip().split("/"):
                    if cge.endswith(".service"):
                        cge = cge[:-8]  # noqa:PLW2901
                        hi = cge.split("@", 1)
                        if hi[0] == "user":
                            continue  # ignore
                        if len(hi) != 1 or hi[0] != "moat-link-host":
                            for h in hi:
                                path.extend(h.split("-"))
                        logger.info("Control Path: %s", path)
                        return Path.build(path)
    raise ServiceNotFound


@define
class SetReady:
    """A handler to signal readiness.

    This duck-types `anyio.abc.TaskStatus` and `anyio.Event`.
    """

    link: Link = field()
    path: Path = field()
    force: bool = field(default=False)
    service_path: Path | None = field(default=None)

    evt: anyio.Event = field(init=False, factory=anyio.Event)
    ready: anyio.Event | None = field(kw_only=True, default=None, repr=False)
    up: bool = field(init=False, default=False, repr=False)
    _value: Any = field(kw_only=True, default=None)

    def set(self):
        """
        We started up.
        """
        if self.up:
            raise RuntimeError("can only start once")
        self.up = True
        self.evt.set()

    def started(self, value: Any = None):
        """
        This mimics `TaskStatus.started`. The value, if any, is added to
        the announcement message as its ``value`` item.
        """
        if value is not None:
            self._value = value
        self.set()

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, value: Any):
        "Set the value to announce"
        self._value = value
        self.evt.set()

    async def monitor(self, *, task_status):
        """
        Watch for other announcements with a different ID.
        """
        async with self.link.d_watch(
            self.path, state=False if self.force else None, mark=True
        ) as mon:
            async for msg in mon:
                if msg is None:
                    if task_status is not None:
                        task_status.started()
                        task_status = None
                    continue

                if msg is NotGiven:
                    raise ServiceCleared(self.path)

                if msg["id"] != self.link.id and await self.link.i_checkid(msg["id"]):
                    raise ServiceSupplanted(self.path)

    async def wait_sr(self):
        await anyio.sleep(5)
        if not self.up:
            warn(f"{self.path} did not (yet?) start")

    async def wait_evt(self, via: anyio.Event):
        await via.wait()
        self.set()

    async def run(self) -> None:
        """
        Send our announcement
        """
        while True:
            data: dict[str, Any] = {"id": self.link.id}
            if self.service_path:
                data["path"] = self.service_path

            # if it's already gone, don't worry.
            if self.value is not None:
                data["value"] = self.value
            if self.up is not None:
                data["up"] = self.up

            await self.link.d_set(self.path, data, retain=True)
            if self.ready is not None:
                await self.link.i_sync()
                self.ready.set()
                self.ready = None

            await self.evt.wait()
            self.evt = anyio.Event()


class FakeReady(TaskStatus):
    """A fake event/TaskStatus that doesn't do anything at all"""

    def set(self):
        pass

    def started(self, value: Any = None):
        pass


@asynccontextmanager
async def announcing(
    link: LinkSender,
    name: Path | None = None,
    *,
    host: Path | str | bool = True,
    force: bool = False,
    service: MsgSender | None = None,
    via: anyio.Event | None = None,
    value: Any = None,
):
    """
    This async context manager broadcasts the availability of a named service.

    Arguments:
        link: the link to use.
        host: a way to override the discovered service name.
        name: additional elements on the announcement
        service: Service to delegate to
        force: Flag to override an existing server
        via: Use this event as a readiness proxy.

    The context manager yields a SetReady object.

    Services are declared by a host prefix and a named path.

    ``host`` can be
    * ``True``: Use the hostname of the system the service runs on.
      This is the default.
    * a string: replace the hostname of the system the service runs on.
      Used for services that should run once in an installation.
    * ``False``: Don't add a hostname. This should not normally be done.

    If ``name`` is `None`, it will be auto-discovered from
    the current systemd unit, by selecting service entries in
    ``/proc/self/cgroups``. It is an error for the result to be empty.
    This requires the ``SYSTEMD_EXEC_PID`` environment variable to
    contain the PID of the current process.

    A :class:`ServiceSupplanted` exception will be raised if/when there is
    a duplicate of the named service on the link (or one appears).

    The ``force`` flag is intended for replacing an existing service. It
    does not ignore a subsequent announcement by some other MoaT-Link
    client.
    """

    try:
        path = await get_service_path(host, name)
    except ServiceNotFound:
        warn("Not running in a service CGroup. Set MT_SERVICE envvar?", NoServiceWarning)
        yield FakeReady()
        return

    if path in link.announced:
        raise RuntimeError("A service announcement is already running")
    link.announced.add(path)

    service_path = Path(gen_ident(12)) if service is not None else None

    async def _delegate(path, service, *, task_status: anyio.TASK_STATUS_IGNORED):
        with link.link.delegate(path, service):
            task_status.started()
            await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        try:
            if service:
                await tg.start(_delegate, service_path, service)
            srv = SetReady(link, path, force, service_path)
            if value is not None:
                srv.value = value
            await tg.start(srv.monitor)
            tg.start_soon(srv.run)
            tg.start_soon(srv.wait_sr)
            if via:
                tg.start_soon(srv.wait_evt, via)

            await link.i_sync()

            yield srv

            # only remove the host entry when we terminated normally.
            await link.d_set(path, retain=True)

        except ServiceSupplanted:
            logger.warning("Service %s on %s already exists", name, host)
            raise
        finally:
            link.announced.discard(path)
            tg.cancel_scope.cancel()


@asynccontextmanager
async def as_service(obj: attrdict | None = None):
    """
    This is a replacement for the legacy :func:`moat.util.as_service`
    helper that also registers the named service with MoaT-Link.
    """
    if obj is None:
        obj = attrdict()
    obj.setdefault("debug", False)
    cfg = ensure_cfg("moat.link", obj.cfg)

    async with (
        _as_service(obj) as mon,
        Link(cfg.link, common=True) as mon.link,
        announcing(mon.link, via=mon.evt),
    ):
        yield mon
