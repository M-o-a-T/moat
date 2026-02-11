"""
Per-series worker for metrics.

Each worker watches a single MoaT-Link value and writes updates
to the corresponding metrics backend.
"""

from __future__ import annotations

import anyio
import logging

from asyncakumuli import Entry

from moat.lib.path import Path

from . import model as _model

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from .backend import Backend
    from .model import MetricsEntry

logger = logging.getLogger(__name__)


async def run_entry(
    link: LinkSender,
    entry: MetricsEntry,
    backend: Backend,
    subpath: Path,
) -> None:
    """Watch one source value and forward it to the metrics backend.

    Args:
        link: an active MoaT-Link sender.
        entry: the configuration node for this series.
        backend: the metrics backend connection.
        subpath: path of this entry relative to the server node
            (used for error reporting).
    """
    source = Path.build(entry.source)
    series = entry.series
    tags = entry.tags
    mode = entry.mode
    attr = entry.attr
    factor = entry.factor
    offset = entry.offset
    t_min = entry.t_min
    t_last: float | None = None

    async with link.d_watch(source) as wp:
        async for raw in wp:
            if t_min is not None:
                t = anyio.current_time()
                if t_last is not None and t_last + t_min > t:
                    continue
                t_last = t

            # Drill into nested data via attr path
            val = raw
            for k in attr:
                try:
                    val = val[k]
                except (KeyError, TypeError, IndexError):
                    logger.warning("Missing attr %r in %s", attr, subpath)
                    break
            else:
                if not isinstance(val, (int, float)):
                    logger.warning("Non-numeric value at %s: %r", subpath, val)
                    continue
                out = val * factor + offset
                e = Entry(series=series, mode=mode, value=out, tags=tags)
                _model._test_hook(e)  # noqa:SLF001
                await backend.put(e)
