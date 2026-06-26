"""
Per-port workers for the Wago controller connector.

Each worker drives a single :class:`~moat.link.wago.model.WagoPort`.
Input workers monitor the Wago controller and publish to MoaT-Link;
output workers watch a MoaT-Link value and write to the controller.
"""

from __future__ import annotations

import anyio
import logging

from moat.util import NotGiven

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from .model import WagoPort

    from typing import Any

logger = logging.getLogger(__name__)


async def run_in(
    link: LinkSender,
    srv: Any,
    entry: WagoPort,
    card: int,
    port: int,
    subpath: Path,
) -> None:
    """Forward Wago input changes to a MoaT-Link destination.

    Args:
        link: Active MoaT-Link sender.
        srv: Connected Wago server.
        entry: Configuration entry for this port.
        card: Card number.
        port: Port number.
        subpath: Path of this entry relative to the server (for naming).
    """
    mode = entry.mode
    dest = entry.dest
    if mode is None or dest is None:
        return

    rest = entry.rest

    if mode == "read":
        async with srv.monitor_input(card, port) as mon:
            async for val in mon:
                await link.d_set(dest, val != rest)
    elif mode == "count":
        intv = entry.interval
        direc = entry.count
        delta = 0
        try:
            old = await link.d_get(dest)
            if isinstance(old, (int, float)):
                delta = old
        except KeyError:
            pass
        async with srv.count_input(card, port, direction=direc, interval=intv) as mon:
            async for val in mon:
                await link.d_set(dest, val + delta)
    else:
        logger.warning("Unknown input mode %r at %s", mode, subpath)


async def run_out(
    link: LinkSender,
    srv: Any,
    entry: WagoPort,
    card: int,
    port: int,
    subpath: Path,
) -> None:
    """Forward MoaT-Link source updates to a Wago output.

    Args:
        link: Active MoaT-Link sender.
        srv: Connected Wago server.
        entry: Configuration entry for this port.
        card: Card number.
        port: Port number.
        subpath: Path of this entry relative to the server (for naming).
    """
    mode = entry.mode
    src = entry.src
    if mode is None or src is None:
        return

    rest = entry.rest
    state = entry.state

    if mode == "write":
        async with link.d_watch(src, mark=False, state=False) as wp:
            async for raw in wp:
                if raw is NotGiven:
                    continue
                val = bool(raw)
                await srv.write_output(card, port, val != rest)
                if state is not None:
                    await link.d_set(state, val)
    elif mode == "oneshot":
        t_on = entry.t_on
        worker: anyio.CancelScope | None = None
        worker_done: anyio.Event | None = None

        async def _cancel_oneshot() -> None:
            nonlocal worker, worker_done
            if worker is not None:
                worker.cancel()
                if worker_done is not None:
                    await worker_done.wait()
                worker = None
                worker_done = None

        async def _run_oneshot(work) -> None:
            nonlocal worker, worker_done
            done_evt = anyio.Event()
            worker_done = done_evt
            try:
                with anyio.CancelScope() as sc:
                    worker = sc
                    logger.error(f"{subpath} on 3")
                    async with work:
                        if state is not None:
                            await link.d_set(state, True)
                        await work.wait()
                    logger.error(f"{subpath} on 5")
            finally:
                if worker is sc:
                    logger.error(f"{subpath} onx 6")
                    worker = None
                    if worker_done is done_evt:
                        worker_done = None
                    done_evt.set()
                with anyio.fail_after(2, shield=True):
                    if state is not None:
                        logger.error(f"{subpath} onx 7")
                        try:
                            v = await srv.read_output(card, port)
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            await link.d_set(state, v != rest)
                        logger.error(f"{subpath} onx 8")
                logger.error(f"{subpath} on 9")

        async def _do_oneshot(val: bool) -> None:
            await _cancel_oneshot()
            if val:
                logger.error(f"{subpath} on 1")
                await _run_oneshot(srv.write_timed_output(card, port, not rest, t_on))
            else:
                logger.error(f"{subpath} off 1")
                await srv.write_output(card, port, rest)
                if state is not None:
                    await link.d_set(state, False)
                logger.error(f"{subpath} off 9")

        mon = await srv.find_monitor(card, port)
        if mon is not None:
            link.link.tg.start_soon(_run_oneshot, mon)

        async with link.d_watch(src, mark=False, state=False) as wp:
            async for val in wp:
                if not isinstance(val, bool):
                    continue
                logger.error(f"{subpath} get {val}")
                link.link.tg.start_soon(_do_oneshot, val)

    elif mode == "pulse":
        t_on = cast(float, entry.t_on)
        t_off = cast(float, entry.t_off)
        worker: anyio.CancelScope | None = None
        worker_done: anyio.Event | None = None

        async def _cancel_pulse() -> None:
            nonlocal worker, worker_done
            if worker is not None:
                worker.cancel()
                if worker_done is not None:
                    await worker_done.wait()
                worker = None
                worker_done = None

        async def _run_pulse(work) -> None:
            nonlocal worker, worker_done
            done_evt = anyio.Event()
            worker_done = done_evt
            try:
                with anyio.CancelScope() as sc:
                    worker = sc
                    async with work:
                        if state is not None:
                            await link.d_set(state, t_on / (t_on + t_off))
                        await work.wait()
            finally:
                if worker is sc:
                    worker = None
                    if worker_done is done_evt:
                        worker_done = None
                    done_evt.set()
                with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            v = await srv.read_output(card, port)
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            await link.d_set(state, v != rest)

        async def _do_pulse(val: bool) -> None:
            await _cancel_pulse()
            if val:
                if t_on is None or t_off is None:
                    raise RuntimeError("t_on or t_off is None")
                await _run_pulse(srv.write_pulsed_output(card, port, not rest, t_on, t_off))
            else:
                await srv.write_output(card, port, rest)
                if state is not None:
                    await link.d_set(state, False)

        mon = await srv.find_monitor(card, port)
        if mon is not None:
            link.link.tg.start_soon(_run_pulse, mon)

        async with link.d_watch(src, mark=False, state=False) as wp:
            async for val in wp:
                if not isinstance(val, bool):
                    continue
                link.link.tg.start_soon(_do_pulse, val)

    else:
        logger.warning("Unknown output mode %r at %s", mode, subpath)
