"""
Per-attribute workers for the 1-Wire (OWFS) bus connector.

The read direction (device→MoaT-Link) is driven by asyncowfs' central
event stream and dispatched from :mod:`moat.link.ow.task`; this module
provides :func:`forward_read`, which publishes a polled value to a
MoaT-Link destination.

The write direction (MoaT-Link→device) is implemented by :func:`run_out`,
which watches a MoaT-Link source path and forwards changes onto the
1-Wire bus.
"""

from __future__ import annotations

import logging

from moat.util import NotGiven, attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from .model import AttrCfg

    from collections.abc import Awaitable, Callable
    from typing import Any

logger = logging.getLogger(__name__)


async def forward_read(link: LinkSender, entry: AttrCfg, val: Any, src: str | None = None) -> None:
    """Publish a polled device value to the entry's MoaT-Link destination.

    If :attr:`~moat.link.ow.model.OwAttr.dest_attr` is set, the value is
    merged into the (possibly pre-existing) dict stored at ``dest``;
    otherwise ``dest`` is replaced wholesale.

    Args:
        link: Active MoaT-Link sender.
        entry: Effective configuration of this attribute.
        val: The value read from the 1-Wire device.
        src: The device's address (``FAMILY.CODE``); recorded as ``src``
            in the item's metadata.
    """
    kw: dict[str, Any] = {} if src is None else {"meta": {"src": src}}
    dest = entry.dest
    if dest is None:
        return
    dest_attr = entry.dest_attr

    if dest_attr is not None:
        try:
            cur = await link.d_get(dest)
        except KeyError:
            cur = attrdict()
        else:
            if not isinstance(cur, dict):
                cur = attrdict()
            else:
                cur = attrdict(cur)
        new = cur._update(dest_attr, val)  # noqa: SLF001
        await link.d_set(dest, new, **kw)
    else:
        await link.d_set(dest, val, **kw)


async def run_out(
    link: LinkSender,
    dev: Any,
    entry: AttrCfg,
    attr_path: Path,
    name: str,
    report: Callable[[Exception | None], Awaitable[None]] | None = None,
) -> None:
    """Forward MoaT-Link source updates onto a 1-Wire device attribute.

    This runs while the device is located. The source's current value is
    written first, so that a device that (re)appears, possibly on another
    bus, gets the current state.

    Args:
        link: Active MoaT-Link sender.
        dev: Located asyncowfs :class:`~asyncowfs.device.Device`.
        entry: Effective configuration of this attribute.
        attr_path: The device-side attribute path to write to.
        name: Name of this entry (for logging).
        report: called with the error when a write fails, or with
            ``None`` when it works.
    """
    src = entry.src
    if src is None:
        return
    src_attr = entry.src_attr

    async with link.d_watch(src, mark=False, state=None) as wp:
        async for val in wp:
            if val is NotGiven:
                continue
            out = val
            if src_attr is not None:
                try:
                    for k in src_attr:
                        out = out[k]
                except (KeyError, TypeError, IndexError):
                    logger.warning(
                        "Attribute %r missing in source value at %s",
                        tuple(src_attr),
                        name,
                    )
                    if report is not None:
                        await report(KeyError(f"{src}: no {src_attr}"))
                    continue
            try:
                await dev.set(*attr_path, value=out)
            except Exception as exc:
                logger.warning("Write to %s failed: %r", name, exc)
                if report is not None:
                    await report(exc)
            else:
                if report is not None:
                    await report(None)
