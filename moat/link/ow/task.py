"""
Main supervisor task for the 1-Wire (OWFS) connector.

Connects to a single owserver and monitors the MoaT-Link configuration
subtree for one server.  Attribute entries are mirrored in both
directions:

* **read** entries are polled by asyncowfs; the resulting values arrive
  on the single :attr:`~asyncowfs.service.Service.events` stream and are
  dispatched to their MoaT-Link destination here.
* **write** entries get a dedicated worker that watches a MoaT-Link
  source and forwards changes onto the bus.

Per-entry write workers are spawned / cancelled as entries appear,
change, or disappear; read polling is (re)configured whenever a device
is located or its entry changes.
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

from moat.util import combine_dict
from moat.lib.path import Path

from .model import OwAttr, OwServer
from .worker import forward_read, run_out

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.link.client import LinkSender

    from collections.abc import Mapping
    from typing import Any

logger = logging.getLogger(__name__)


def _canon_attr(attr: Any) -> tuple[str, ...]:
    """Canonicalise a polled attribute into a string tuple for matching.

    asyncowfs reports single attributes as strings (``"temperature"``)
    and nested ones either as slash-joined strings or as the tuple that
    was originally passed to :meth:`~asyncowfs.device.Device.set_polling_interval`.
    """
    if isinstance(attr, str):
        attr = attr.split("/")
    return tuple(str(x) for x in attr)


async def task(
    link: LinkSender,
    cfg: Mapping,
    server_name: str,
    *,
    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Run the 1-Wire connector for one owserver.

    Args:
        link: an active MoaT-Link sender.
        cfg: the ``link.ow`` configuration section.
        server_name: the server entry name inside the config subtree.
        task_status: task-status for ``tg.start``.
    """
    prefix = Path.build(cfg["prefix"])
    server_path = prefix / server_name

    server_data = await link.d_get(server_path)
    if not isinstance(server_data, dict):
        server_data = {}
    srv_cfg = combine_dict(
        server_data.get("server", {}),
        cfg.get("server_default", {}),
    )

    async with OWFS() as ow, anyio.create_task_group() as tg:
        devs: dict[tuple[int, int], Any] = {}
        entries: dict[Path, OwAttr] = {}
        by_key: dict[tuple[int, int, tuple[str, ...]], Path] = {}
        writers: dict[Path, anyio.CancelScope] = {}

        def _fc(p: Path) -> tuple[int, int]:
            return int(p[0]), int(p[1])

        def _attr_path(p: Path) -> Path:
            return Path.build(tuple(p)[2:])

        def _key(p: Path) -> tuple[int, int, tuple[str, ...]]:
            f, c = _fc(p)
            return f, c, _canon_attr(tuple(p)[2:])

        def _cancel_writer(p: Path) -> None:
            sc = writers.pop(p, None)
            if sc is not None:
                sc.cancel()

        async def _activate(p: Path, n: OwAttr) -> None:
            """(Re)configure one entry: writer and/or polling."""
            _cancel_writer(p)
            entries[p] = n
            by_key[_key(p)] = p

            dev = devs.get(_fc(p))
            if dev is None:
                return  # device not located yet; activated on arrival

            ap = _attr_path(p)
            # Clear any stale polling from a previous incarnation.
            try:
                await dev.set_polling_interval(ap, 0)
            except Exception:
                logger.debug("Clear-poll for %s failed", p, exc_info=True)

            if n.is_read:
                intv = n.interval
                if intv and intv > 0:
                    try:
                        await dev.set_polling_interval(ap, intv)
                    except Exception as exc:
                        logger.warning("Polling setup for %s failed: %r", p, exc)
            elif n.is_write:
                apw = ap

                async def _run(
                    *,
                    task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
                ) -> None:
                    with anyio.CancelScope() as sc:
                        writers[p] = sc
                        task_status.started()
                        try:
                            await run_out(link, dev, n, apw, p)
                        except Exception:
                            logger.exception("Writer for %s failed", p)
                        finally:
                            if writers.get(p) is sc:
                                del writers[p]

                await tg.start(_run)

        def _deactivate(p: Path) -> None:
            """Tear down one entry."""
            _cancel_writer(p)
            n = entries.pop(p, None)
            if n is None:
                return
            if by_key.get(_key(p)) is p:
                del by_key[_key(p)]
            if n.is_read:
                dev = devs.get(_fc(p))
                if dev is not None:
                    tg.start_soon(_safe_clear_poll, dev, _attr_path(p), p)

        async def _safe_clear_poll(dev: Any, ap: Path, p: Path) -> None:
            try:
                await dev.set_polling_interval(ap, 0)
            except Exception:
                logger.debug("Clear-poll for %s failed", p, exc_info=True)

        async def _on_located(dev: Any) -> None:
            key = int(dev.family), int(dev.code)
            devs[key] = dev
            for p, n in list(entries.items()):
                if _fc(p) == key:
                    await _activate(p, n)

        def _on_not_found(dev: Any) -> None:
            key = int(dev.family), int(dev.code)
            devs.pop(key, None)
            for p in list(writers):
                if _fc(p) == key:
                    _cancel_writer(p)

        async def _on_value(dev: Any, attr: Any, val: Any) -> None:
            key = int(dev.family), int(dev.code), _canon_attr(attr)
            p = by_key.get(key)
            if p is None:
                return
            n = entries.get(p)
            if n is not None and n.is_read:
                try:
                    await forward_read(link, n, val)
                except Exception as exc:
                    logger.warning("Forward read for %s failed: %r", p, exc)

        async def mon_events(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            async with ow.events as events:
                task_status.started()
                async for msg in events:
                    try:
                        if isinstance(msg, DeviceValue):
                            await _on_value(msg.device, msg.attribute, msg.value)
                        elif isinstance(msg, DeviceLocated):
                            await _on_located(msg.device)
                        elif isinstance(msg, DeviceNotFound):
                            _on_not_found(msg.device)
                        elif isinstance(msg, DeviceException):
                            logger.warning(
                                "OWFS error at %s.%s: %r",
                                msg.device,
                                msg.attribute,
                                msg.exception,
                            )
                    except Exception:
                        logger.exception("Event processing failed for %r", msg)

        # Start the event reader before adding the server so that the
        # initial scan's device-location events are not lost.
        await tg.start(mon_events)
        await ow.add_server(name=server_name, **srv_cfg)

        async with link.d_watch(
            server_path,
            subtree=True,
            mark=True,
            cls=OwServer,
        ) as mon:
            task_status.started()

            async for msg in mon:
                if msg is None:
                    continue
                p, _d = msg
                if not p:
                    continue

                node = mon.nodes.get(p)
                if isinstance(node, OwAttr) and node.is_complete():
                    await _activate(p, node)
                else:
                    _deactivate(p)

        tg.cancel_scope.cancel()
