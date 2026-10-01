"""
Main task for the 1-Wire (OWFS) connector.

One `asyncowfs.OWFS` instance talks to all owservers. It tracks devices
by their (globally unique) ID, so a device that moves to another bus
keeps its polling settings; the configuration is keyed by device too.

* Each owserver is announced and run like a gate (see
  `moat.link.gate.AnnouncedJob`): it's added to the OWFS instance while
  this process holds its announcement.
* Read mappings set the device's polling interval; asyncowfs reports the
  values on its event stream, and they're published here.
* Write mappings get a worker while their device is located.
"""

from __future__ import annotations

import anyio
import logging

from asyncowfs import OWFS
from asyncowfs.event import (
    DeviceException,
    DeviceLocated,
    DeviceNotFound,
    DeviceValue,
)

from moat.util import NotGiven, combine_dict
from moat.lib.path import Path
from moat.link.gate import AnnouncedJob

from .model import SERVER, OwRoot, fmt_device
from .worker import forward_read, run_out

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from asyncowfs.service import Service

    from moat.link.client import Link

    from .model import AttrCfg

    from collections.abc import Iterable, Sequence
    from typing import Any

logger = logging.getLogger(__name__)

Key = tuple[int, int, Path]
"family, code, attribute path"


def _canon_attr(attr: Any) -> tuple[str, ...]:
    """Canonicalise an attribute path for matching polled values.

    asyncowfs reports single attributes as strings (``"temperature"``)
    and nested ones either as slash-joined strings or as the tuple that
    was originally passed to `asyncowfs.device.Device.set_polling_interval`.
    """
    if isinstance(attr, str):
        attr = attr.split("/")
    return tuple(str(x) for x in attr)


def _name(key: Key) -> str:
    f, c, a = key
    return f"{fmt_device(f, c)}.{a}" if len(a) else fmt_device(f, c)


class _Devices:
    """Apply the device configuration to the devices asyncowfs finds."""

    root: OwRoot | None = None

    def __init__(self, link: Link, prefix: Path, tg: TaskGroup) -> None:
        self.link = link
        self.prefix = prefix
        self.tg = tg
        self.devs: dict[tuple[int, int], Any] = {}
        "All devices seen so far. asyncowfs keeps them across bus changes."
        self.active: dict[Key, AttrCfg] = {}
        self.by_canon: dict[tuple[int, int, tuple[str, ...]], Key] = {}
        self.writers: dict[Key, anyio.CancelScope] = {}

    # configuration

    async def watch_cfg(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED):
        """Watch the configuration, (re)apply what changes."""
        async with self.link.d_watch(self.prefix, subtree=True, mark=True, cls=OwRoot) as mon:
            self.root = mon.nodes
            async for msg in mon:
                if msg is None:
                    task_status.started()
                    continue
                p, _d = msg
                if not len(p) or not isinstance(p[0], int):
                    continue  # the root, or the servers
                for key in self._affected(p):
                    await self.apply(key)

    def _affected(self, p: Path) -> Iterable[Key]:
        "The mappings affected by a change at @p."
        f = p[0]
        c = p[1] if len(p) > 1 else None
        if not isinstance(f, int) or (c is not None and not isinstance(c, int)):
            return ()
        if len(p) > 2:
            assert c is not None
            return ((f, c, Path.build(p[2:])),)
        assert self.root is not None
        keys = set(self.root.attrs(f, c))
        keys.update(k for k in self.active if k[0] == f and (c is None or k[1] == c))
        return keys

    async def apply(self, key: Key) -> None:
        """Bring one mapping in line with its configuration."""
        assert self.root is not None
        new = self.root.attr_cfg(*key)
        if new is not None and not new.is_complete():
            new = None
        old = self.active.get(key)
        if new == old:
            return
        f, c, a = key
        dev = self.devs.get((f, c))

        if old is not None:
            del self.active[key]
            self.by_canon.pop((f, c, _canon_attr(a)), None)
            self._stop_writer(key)
            if dev is not None and old.is_read:
                await self._poll(dev, key, 0)

        if new is None:
            return
        self.active[key] = new
        self.by_canon[(f, c, _canon_attr(a))] = key
        if dev is None:
            return  # set up when the device is located
        if new.is_read:
            await self._poll(dev, key, new.interval or 0)
        if new.is_write and dev.bus is not None:
            await self._start_writer(dev, key, new)

    async def _poll(self, dev: Any, key: Key, interval: float) -> None:
        # asyncowfs remembers the interval while the device isn't located.
        try:
            await dev.set_polling_interval(key[2], interval)
        except Exception as exc:
            logger.warning("Polling setup for %s failed: %r", _name(key), exc)

    async def _start_writer(self, dev: Any, key: Key, cfg: AttrCfg) -> None:
        self._stop_writer(key)

        async def _run(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            with anyio.CancelScope() as sc:
                self.writers[key] = sc
                task_status.started()
                try:
                    await run_out(self.link, dev, cfg, key[2], _name(key))
                except Exception:
                    logger.exception("Writer for %s failed", _name(key))
                finally:
                    if self.writers.get(key) is sc:
                        del self.writers[key]

        await self.tg.start(_run)

    def _stop_writer(self, key: Key) -> None:
        sc = self.writers.pop(key, None)
        if sc is not None:
            sc.cancel()

    # OWFS events

    async def run_events(
        self, ow: Service, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED
    ) -> None:
        """Process the events from asyncowfs."""
        async with ow.events as events:
            task_status.started()
            async for msg in events:
                try:
                    if isinstance(msg, DeviceValue):
                        await self._on_value(msg.device, msg.attribute, msg.value)
                    elif isinstance(msg, DeviceLocated):
                        await self._on_located(msg.device)
                    elif isinstance(msg, DeviceNotFound):
                        self._on_not_found(msg.device)
                    elif isinstance(msg, DeviceException):
                        logger.warning(
                            "OWFS error at %s.%s: %r", msg.device, msg.attribute, msg.exception
                        )
                except Exception:
                    logger.exception("Event processing failed for %r", msg)

    async def _on_located(self, dev: Any) -> None:
        fc = int(dev.family), int(dev.code)
        logger.info("Device %s found on %s", fmt_device(*fc), dev.bus)
        known = fc in self.devs
        self.devs[fc] = dev
        for key, cfg in list(self.active.items()):
            if key[:2] != fc:
                continue
            if cfg.is_read and not known:
                await self._poll(dev, key, cfg.interval or 0)
            if cfg.is_write:
                await self._start_writer(dev, key, cfg)

    def _on_not_found(self, dev: Any) -> None:
        fc = int(dev.family), int(dev.code)
        logger.info("Device %s lost", fmt_device(*fc))
        for key in list(self.writers):
            if key[:2] == fc:
                self._stop_writer(key)

    async def _on_value(self, dev: Any, attr: Any, val: Any) -> None:
        key = self.by_canon.get((int(dev.family), int(dev.code), _canon_attr(attr)))
        if key is None:
            return
        cfg = self.active.get(key)
        if cfg is not None and cfg.is_read:
            try:
                await forward_read(self.link, cfg, val)
            except Exception as exc:
                logger.warning("Forward read for %s failed: %r", _name(key), exc)


class _ServerJob(AnnouncedJob):
    """Announce one owserver; add it to the OWFS instance while we hold it."""

    def __init__(
        self, cfg: dict[str, Any], link: Link, path: Path, ow: Service, srv: Mapping[str, Any]
    ) -> None:
        super().__init__(cfg, link, path, "ow")
        self.name = str(path[-1])
        self.ow = ow
        self.srv = srv
        self.changed = anyio.Event()

    async def work(self, *, task_status) -> None:
        srv = dict(self.srv)
        # asyncowfs' own periodic scan (``add_server(scan=…)``) re-acquires
        # the scan lock it already holds. Rescan here instead.
        scan = srv.pop("scan", None)
        server = await self.ow.add_server(name=self.name, **srv)
        try:
            task_status.started()
            while not self.changed.is_set():
                with anyio.move_on_after(scan or float("inf")):
                    await self.changed.wait()
                if scan and not self.changed.is_set():
                    await server.scan_now()
        finally:
            with anyio.CancelScope(shield=True):
                await server.drop()


def _srv_cfg(cfg: Mapping[str, Any], d: Any) -> dict[str, Any] | None:
    "The owserver settings of a server entry, or None if there's no host."
    srv = d.get(SERVER) if isinstance(d, Mapping) else None
    if not isinstance(srv, Mapping) or not srv.get("host"):
        return None
    return combine_dict(srv, cfg.get("server_default", {}))


async def run_servers(
    cfg: dict[str, Any],
    link: Link,
    ow: Service,
    *,
    only: Sequence[str] = (),
    force: bool = False,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Announce and run the owservers (all of them, or those in @only).

    A server is restarted when its settings change and dropped when its
    entry is deleted. One that another live process has announced is
    skipped until that announcement goes away, unless @force is set (which
    only applies to the servers that exist at startup).
    """
    ocfg = cfg["link"]["ow"]
    spath = Path.build(ocfg["prefix"]) / SERVER
    jobs: dict[str, _ServerJob] = {}
    current: dict[str, dict[str, Any]] = {}

    async with anyio.create_task_group() as tg:

        async def _run(job: _ServerJob, force: bool) -> None:
            name = job.name
            try:
                await job.run(force)
            finally:
                if jobs.get(name) is job:
                    del jobs[name]
            # The job ended because its settings changed.
            _check(name, False)

        def _check(name: str, force: bool) -> None:
            srv = current.get(name)
            job = jobs.get(name)
            if job is not None:
                if srv == job.srv:
                    job.retry()
                    return
                if job.idle and job.scope is not None:
                    job.scope.cancel()  # not running, nothing to clean up
                    del jobs[name]
                else:
                    job.changed.set()  # the job will stop by itself, then re-check
                    return
            if srv is None:
                return
            jobs[name] = job = _ServerJob(cfg, link, spath / name, ow, srv)
            tg.start_soon(_run, job, force)

        async with link.d_watch(spath, subtree=True, state=None, mark=True) as mon:
            initial = True
            async for msg in mon:
                if msg is None:
                    initial = False
                    for name in list(current):
                        _check(name, force)
                    for job in list(jobs.values()):
                        await job.settled.wait()
                    task_status.started()
                    continue
                p, d = msg
                if len(p) != 1:
                    continue
                name = p[0]
                if not isinstance(name, str) or (only and name not in only):
                    continue
                srv = None if d is NotGiven else _srv_cfg(ocfg, d)
                if srv is None:
                    if d is not NotGiven:
                        logger.warning("Server %s: no host set", name)
                    current.pop(name, None)
                else:
                    current[name] = srv
                if not initial:
                    _check(name, False)


async def task(
    link: Link,
    cfg: dict[str, Any],
    only: Sequence[str] = (),
    *,
    force: bool = False,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the 1-Wire connector.

    Args:
        link: an active MoaT-Link client.
        cfg: the global configuration.
        only: the owservers to run; default: all of them.
        force: take over servers announced by another process.
        task_status: started when the servers found at startup are
            running, waiting for another process, or have crashed.
    """
    prefix = Path.build(cfg["link"]["ow"]["prefix"])
    async with OWFS() as ow, anyio.create_task_group() as tg:
        devs = _Devices(link, prefix, tg)
        # Start the event reader before adding servers, so that the
        # initial scan's device-location events are not lost.
        await tg.start(devs.run_events, ow)
        await tg.start(devs.watch_cfg)
        await run_servers(cfg, link, ow, only=only, force=force, task_status=task_status)
