"""
MoaT-Link services announce themselves with defined names.
"""

from __future__ import annotations

import anyio
import logging
import os
import platform
import warnings
import weakref
from anyio.abc import TaskStatus
from contextlib import asynccontextmanager

from moat.util import CFG, NotGiven, P, Path, attrdict, gen_ident
from moat.util import as_service as _as_service

from .client import Link
from .exceptions import ServiceNotFound, ServiceNotStarted, ServiceSupplanted

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.cmd.base import MsgSender
    from moat.util.path import PathElem

    from .client import LinkSender

    from typing import Any

__all__ = ["announcing"]

logger = logging.getLogger(__name__)

# TODO when to warn vs. when to log a warning


async def get_service_path(host: Path | str | bool):
    path: list[PathElem]
    match host:
        case True:
            path = [platform.node()]
        case False:
            path = []
        case Path():
            path = list(host.raw)
        case str():
            path = [host]
        case _:
            raise TypeError("Host must be bool/path/str, not {host !r}.")

    if int(os.environ.get("SYSTEMD_EXEC_PID", "0")) == os.getpid():
        async with await anyio.Path("/proc/self/cgroup").open("r") as cgf:
            async for cg in cgf:
                for cge in cg.strip().split("/"):
                    if cge.endswith(".service"):
                        cge = cge[:-8]  # noqa:PLW2901
                        hi = cge.split("@", 1)
                        if hi[0] == "user":
                            continue  # ignore
                        if len(hi) != 1 or hi[0] != "moat-link-host":
                            path.extend(hi)
                        return path
    raise ServiceNotFound


class SetReady(TaskStatus):
    """A fake event/TaskStatus to signal readiness"""

    value: Any = None

    def __init__(self, ann: anyio.Event, host, name):
        self.evt = anyio.Event()
        self.ann = ann
        self.host = host
        self.name = name

    def set(self):  # pylint:disable=missing-function-docstring
        "Set the event."
        self.evt.set()

    async def announce(self, value: Any = None):
        """
        Store the value if any, set the event, wait for the announcement to
        be transmitted.
        """
        self.started(value)
        await self.ann.wait()

    def started(self, value: Any = None):
        """
        Mock task_status.started. A value, if any, is added to
        the Host message as its ``val`` item.
        """
        self.value = value
        self.set()

    def __del__(self):
        """
        Complain if the SR was unused.
        """
        try:
            if not self.evt.is_set():
                warnings.warn(
                    f"event {self.name} on {self.host} freed before announcing",
                    ServiceNotStarted,
                )
        except Exception:  # noqa:S110
            pass

    def warn(self, s: str):
        logger.warning("Service %s on %s %s", self.name, self.host, s)


class _csr:
    # This object caches a SetReady until it is called.
    # The idea is to be able to atomically yield *and* delete our reference to a SR.

    def __init__(self, sr: SetReady):
        self.sr = sr

    def __call__(self):
        sr = self.sr
        del self.sr
        return sr

    def __del__(self):
        try:
            # Don't worry if any of these no longer work.
            self.sr.evt.set()
        except Exception:  # noqa:S110
            pass


@asynccontextmanager
async def announcing(
    link: LinkSender,
    name: Path | None = None,
    *,
    host: Path | str | bool = True,
    force: bool = False,
    service: MsgSender | None = None,
):
    """
    This async context manager broadcasts the availability of a named service.

    Arguments:
        link: the link to use.
        host: a way to override the discovered service name.
        name: additional elements on the announcement
        service: Service to delegate to
        force: Flag to override an existing server

    The CM yields a SetReady object. You must call one of its ``.set``,
    ``annonce`` or ``started`` methods to start the announcement.

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

    if service is not None:
        path = Path(gen_ident(12))

    async def run_announce(srv: Path, sr: SetReady, rdy: anyio.Event) -> None:
        # Send our announcement when ready
        evt = sr.evt
        csr = weakref.ref(sr)
        del sr

        try:
            await evt.wait()
        except BaseException:
            # If we're cancelled (or whatever), set the event. The SR will
            # still be referenced at this point, because the frame that
            # called "announcing" is somewhere in the exception chain, thus
            # this is guaranteed to run before SR.__del__.
            evt.set()
            raise

        data: dict[str, Any] = {"id": link.id}
        if service:
            data["path"] = path

        # if it's already gone, don't worry.
        sr = csr()
        if sr is not None and sr.value is not None:
            data["val"] = sr.value
        await link.d_set(srv, data, retain=True)
        await link.i_sync()
        rdy.set()

    async def monitor_service(srv: Path):
        # Watch for others
        async with link.d_watch(srv, state=False if force else NotGiven) as mon:
            async for msg in mon:
                if msg["id"] != link.id and await link.i_checkid(msg["id"]):
                    raise ServiceSupplanted(srv)

    async def wait_sr(sr: SetReady):
        csr = weakref.ref(sr)
        del sr
        await anyio.sleep(5)
        try:
            csr().warn("did not start")
        except Exception:  # noqa:S110
            pass

    async def _delegate(path, service, *, task_status: anyio.TASK_STATUS_IGNORED):
        with link.link.delegate(path, service):
            task_status.started()
            await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        try:
            rdy = anyio.Event()
            tm = anyio.current_time()
            sr = SetReady(rdy, host, name)
            csr = _csr(sr)
            evt = sr.evt
            srv = P("run.host") + ((await get_service_path(host)) if name is None else name)
            if service:
                await tg.start(_delegate, path, service)
            tg.start_soon(monitor_service, srv)
            tg.start_soon(run_announce, srv, sr, rdy)
            tg.start_soon(wait_sr, sr)
            del sr

            await link.i_sync()

            yield csr()
            if not evt.is_set():
                evt.set()
                logger.warning("Service %s on %s did not start", name, host)

        except ServiceSupplanted:
            logger.warning("Service %s on %s already exists", name, host)
            raise
        except BaseException:
            if anyio.current_time() - tm > 5 and not evt.is_set():
                logger.warning("Service %s on %s did not starting", name, host)
            raise
        finally:
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
    async with (
        _as_service(obj) as mon,
        Link(CFG["link"], common=True) as mon.link,
        announcing(mon.link),
    ):
        yield mon
