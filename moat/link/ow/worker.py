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

    from .model import OwAttr

    from typing import Any

logger = logging.getLogger(__name__)


async def forward_read(link: LinkSender, entry: OwAttr, val: Any) -> None:
    """Publish a polled device value to the entry's MoaT-Link destination.

    If :attr:`~moat.link.ow.model.OwAttr.dest_attr` is set, the value is
    merged into the (possibly pre-existing) dict stored at ``dest``;
    otherwise ``dest`` is replaced wholesale.

    Args:
        link: Active MoaT-Link sender.
        entry: Configuration entry for this attribute.
        val: The value read from the 1-Wire device.
    """
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
        await link.d_set(dest, new)
    else:
        await link.d_set(dest, val)


async def run_out(
    link: LinkSender,
    dev: Any,
    entry: OwAttr,
    attr_path: Path,
    subpath: Path,
) -> None:
    """Forward MoaT-Link source updates onto a 1-Wire device attribute.

    Args:
        link: Active MoaT-Link sender.
        dev: Located asyncowfs :class:`~asyncowfs.device.Device`.
        entry: Configuration entry for this attribute.
        attr_path: The device-side attribute path to write to.
        subpath: Path of this entry relative to the server (for logging).
    """
    src = entry.src
    if src is None:
        return
    src_attr = entry.src_attr

    async with link.d_watch(src, mark=False, state=False) as wp:
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
                        subpath,
                    )
                    continue
            try:
                await dev.set(*attr_path, value=out)
            except Exception as exc:
                logger.warning("Write to %s failed: %r", subpath, exc)
