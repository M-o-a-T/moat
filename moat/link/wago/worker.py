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

from typing import TYPE_CHECKING

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
        _work: anyio.CancelScope | None = None
        _work_done: anyio.Event | None = None

        async def _cancel_work() -> None:
            nonlocal _work, _work_done
            if _work is not None:
                _work.cancel()
                if _work_done is not None:
                    await _work_done.wait()
                _work = None
                _work_done = None

        async def _do_oneshot(val: bool) -> None:
            nonlocal _work, _work_done
            if val:
                await _cancel_work()
                done_evt = anyio.Event()
                _work_done = done_evt
                with anyio.CancelScope() as sc:
                    _work = sc
                    async with srv.write_timed_output(card, port, not rest, t_on) as work:
                        if state is not None:
                            await link.d_set(state, True)
                        await work.wait()
                if _work is sc:
                    _work = None
                    if _work_done is done_evt:
                        _work_done = None
                    done_evt.set()
                with anyio.fail_after(2, shield=True):
                    if state is not None:
                        try:
                            v = await srv.read_output(card, port)
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            await link.d_set(state, v != rest)
            else:
                await _cancel_work()
                await srv.write_output(card, port, rest)
                if state is not None:
                    await link.d_set(state, False)

        async with link.d_watch(src, mark=False, state=False) as wp:
            async for raw in wp:
                if raw is NotGiven:
                    continue
                await _do_oneshot(bool(raw))

    elif mode == "pulse":
        t_on = entry.t_on
        t_off = entry.t_off
        _work: anyio.CancelScope | None = None
        _work_done: anyio.Event | None = None

        async def _cancel_pulse() -> None:
            nonlocal _work, _work_done
            if _work is not None:
                _work.cancel()
                if _work_done is not None:
                    await _work_done.wait()
                _work = None
                _work_done = None

        async def _do_pulse(val: bool) -> None:
            nonlocal _work, _work_done
            if val:
                await _cancel_pulse()
                done_evt = anyio.Event()
                _work_done = done_evt
                try:
                    with anyio.CancelScope() as sc:
                        _work = sc
                        if t_on is None or t_off is None:
                            raise RuntimeError("t_on or t_off is None")
                        async with srv.write_pulsed_output(
                            card, port, not rest, t_on, t_off
                        ) as work:
                            if state is not None:
                                await link.d_set(state, t_on / (t_on + t_off))
                            await work.wait()
                finally:
                    if _work is sc:
                        _work = None
                        if _work_done is done_evt:
                            _work_done = None
                        done_evt.set()
                    with anyio.fail_after(2, shield=True):
                        if state is not None:
                            try:
                                v = await srv.read_output(card, port)
                            except anyio.ClosedResourceError:
                                pass
                            else:
                                await link.d_set(state, v != rest)
            else:
                await _cancel_pulse()
                await srv.write_output(card, port, rest)
                if state is not None:
                    await link.d_set(state, False)

        async with link.d_watch(src, mark=False, state=False) as wp:
            async for raw in wp:
                if raw is NotGiven:
                    continue
                await _do_pulse(bool(raw))

    else:
        logger.warning("Unknown output mode %r at %s", mode, subpath)
