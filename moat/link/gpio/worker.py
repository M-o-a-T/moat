"""
Per-line workers for the GPIO connector.

Input workers (``type=input``) monitor a GPIO line and publish decoded
values to a MoaT-Link destination.  Three input modes are supported:

* ``read``: forward debounced line state changes.
* ``count``: accumulate pulse counts and report periodically.
* ``button``: decode button press sequences (short/long/multi-click).

Output workers (``type=output``) watch a MoaT-Link source and drive
the GPIO line accordingly.  Three output modes are supported:

* ``write``: directly mirror the source value.
* ``oneshot``: pulse high for ``t_on`` seconds, then revert.
* ``pulse``: continuously pulse with duty cycle ``t_on``/``t_off``.
"""

from __future__ import annotations

import anyio
import logging

import moat.lib.gpio as gpio
from moat.util import NotGiven, combine_dict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from .model import GpioLine

    from typing import Any

logger = logging.getLogger(__name__)


def _DIR(d):
    """Translate a direction flag to a :class:`gpio.Edge`."""
    if d is None:
        return gpio.Edge.BOTH
    if d:
        return gpio.Edge.RISING
    return gpio.Edge.FALLING


# ── Input workers ────────────────────────────────────────────────


async def run_in(
    link: LinkSender,
    chip: Any,
    entry: GpioLine,
    line_num: int,
    subpath: Path,
    cfg: dict[str, Any],
) -> None:
    """Forward GPIO line state changes to a MoaT-Link destination.

    Dispatches to :func:`_poll_task`, :func:`_count_task`, or
    :func:`_button_task` depending on ``entry.mode``.

    Args:
        link: Active MoaT-Link sender.
        chip: Open GPIO chip handle.
        entry: Configuration entry for this line.
        line_num: Line number on the chip.
        subpath: Path of this entry (for logging).
        cfg: Global ``link.gpio`` defaults, merged with per-line config.
    """
    mode = entry.mode
    dest = entry.dest
    if mode is None or dest is None:
        return

    lc = combine_dict(entry.data_ if isinstance(entry.data_, dict) else {}, cfg)

    if mode == "read":
        await _poll_task(link, chip, line_num, dest, lc, subpath)
    elif mode == "count":
        await _count_task(link, chip, line_num, dest, lc, subpath)
    elif mode == "button":
        await _button_task(link, chip, line_num, dest, lc, subpath)
    else:
        logger.warning("Unknown input mode %r at %s", mode, subpath)


async def _poll_task(
    link: LinkSender,
    chip: Any,
    line_num: int,
    dest: Path,
    lc: dict[str, Any],
    subpath: Path,  # noqa: ARG001
) -> None:
    """Monitor a line and forward debounced state changes."""
    negate = lc.get("low", False)
    change = lc.get("change", None)
    skip = lc.get("skip", True)
    bounce = lc.get("t_bounce", 0.05)

    wire = chip.line(line_num)
    with wire.monitor(gpio.Edge.BOTH) as mon:
        old_value = mon.value

        async def set_value(value: bool) -> None:
            if negate:
                value = not value
            if change is None or value == change:
                await link.d_set(dest, value)

        await set_value(old_value)
        mon_iter = mon.__aiter__()
        while True:
            e = await mon_iter.__anext__()

            if not skip:
                await set_value(not old_value)

            with anyio.move_on_after(bounce):
                while True:
                    e = await mon_iter.__anext__()

            if old_value == e.value:
                if not skip:
                    await set_value(old_value)
            else:
                if skip:
                    await set_value(e.value)
                old_value = e.value


async def _count_task(
    link: LinkSender,
    chip: Any,
    line_num: int,
    dest: Path,
    lc: dict[str, Any],
    subpath: Path,  # noqa: ARG001
) -> None:
    """Count pulses on a line and report periodically."""
    intv = lc.get("interval", 1)
    direc = lc.get("count", True)
    bounce = lc.get("t_bounce", 0.05)

    async def get_value() -> float:
        try:
            val = await link.d_get(dest)
        except KeyError:
            return 0.0
        if not isinstance(val, (int, float)):
            return 0.0
        return float(val)

    val = await get_value()

    wire = chip.line(line_num)
    with wire.monitor(_DIR(None)) as mon:
        i = mon.__aiter__()
        t = anyio.current_time()
        d: int = 0
        armed = False
        value = mon.value
        debounce = True

        while True:
            if not armed:
                await i.__anext__()
                debounce = True
                t = anyio.current_time()
                tm = intv
            else:
                tm = max(0, t + intv - anyio.current_time())
            try:
                with anyio.fail_after(bounce if debounce else tm):
                    await i.__anext__()
            except TimeoutError:
                if debounce:
                    debounce = False
                    if mon.value != value:
                        value = mon.value
                        if direc is not (not value):
                            if not armed:
                                d = 1
                                val += d
                                await link.d_set(dest, val)
                                d = 0
                                armed = True
                            else:
                                d += 1
                elif d == 0:
                    armed = False
                else:
                    val += d
                    await link.d_set(dest, val)
                    d = 0
                    armed = True
            else:
                debounce = True


async def _button_task(
    link: LinkSender,
    chip: Any,
    line_num: int,
    dest: Path,
    lc: dict[str, Any],
    subpath: Path,  # noqa: ARG001
) -> None:
    """Decode button-press sequences and publish them."""
    negate = lc.get("low", False)
    skip = lc.get("skip", True)
    bounce = lc.get("t_bounce", 0.05)
    idle = lc.get("t_idle", 1.5)
    idle_h = lc.get("t_idle_on", idle)
    idle_clear = lc.get("t_clear", 30)
    count = lc.get("count", True)
    flow = lc.get("flow", False)

    wire = chip.line(line_num)
    with wire.monitor(gpio.Edge.BOTH) as mon:
        ival = mon.value
        mon_iter = mon.__aiter__()

        def td(a, b):
            a = a.timestamp
            b = b.timestamp
            return a[0] - b[0] + (a[1] - b[1]) / 1000000000

        def inv(x):
            if x is None:
                return x
            if negate:
                return not x
            return bool(x)

        count = inv(count)

        async def record(e1, ival):
            res: list[int] = []
            e1.value = None
            e0 = e1
            e2 = None
            flow_bounce = flow
            while True:
                try:
                    with anyio.fail_after(bounce):
                        e2 = await mon_iter.__anext__()
                except TimeoutError:
                    pass
                else:
                    e1 = e2
                    if flow_bounce and td(e1, e0) > bounce:
                        flow_bounce = False
                        await link.d_set(
                            dest,
                            {
                                "start": inv(ival),
                                "seq": res + [0],
                                "end": inv(e1.value),
                                "t": bounce,
                                "flow": True,
                            },
                        )
                    continue

                if e2 is None:
                    e2 = e1

                if e0.value is None:
                    e0.value = not ival

                if e1.value != e0.value:
                    if skip or td(e1, e0) < bounce:
                        e1 = e0
                    else:
                        if count is not bool(e1.value):
                            res.append(int(td(e1, e0) / bounce))
                            if flow:
                                await link.d_set(
                                    dest,
                                    {
                                        "start": not ival,
                                        "seq": res,
                                        "end": inv(e1.value),
                                        "t": bounce,
                                        "flow": True,
                                    },
                                )
                        e0 = e1

                try:
                    with anyio.fail_after((idle_h if inv(e1.value) else idle) - bounce):
                        e2 = await mon_iter.__anext__()
                except TimeoutError:
                    if count is not bool(e1.value):
                        res.append(0)
                    return ival, inv(ival), res, inv(e1.value)

                if count is not (not bool(e1.value)):
                    res.append(int(td(e2, e0) / bounce))

                e2.value = not e1.value
                e0 = e1 = e2
                if flow:
                    await link.d_set(
                        dest,
                        {
                            "start": not ival,
                            "seq": res,
                            "end": inv(e2.value),
                            "t": bounce,
                            "flow": True,
                        },
                    )
                flow_bounce = flow

        clear = True
        while True:
            if clear and idle_clear:
                try:
                    with anyio.fail_after(idle_clear):
                        e = await mon.__anext__()
                except TimeoutError:
                    await link.d_set(dest, False)
                    clear = False
                    continue
            else:
                e = await mon.__anext__()
            ival, start_val, res, end_val = await record(e, ival)
            if not res:
                continue
            await link.d_set(
                dest,
                {
                    "start": start_val,
                    "seq": res,
                    "end": end_val,
                    "t": bounce,
                },
            )
            clear = True


# ── Output workers ───────────────────────────────────────────────


async def run_out(
    link: LinkSender,
    chip: Any,
    entry: GpioLine,
    line_num: int,
    subpath: Path,
    cfg: dict[str, Any],
) -> None:
    """Forward MoaT-Link source updates onto a GPIO line.

    Dispatches to :func:`_set_value`, :func:`_oneshot_value`, or
    :func:`_pulse_value` depending on ``entry.mode``.

    Args:
        link: Active MoaT-Link sender.
        chip: Open GPIO chip handle.
        entry: Configuration entry for this line.
        line_num: Line number on the chip.
        subpath: Path of this entry (for logging).
        cfg: Global ``link.gpio`` defaults, merged with per-line config.
    """
    mode = entry.mode
    src = entry.src
    if mode is None or src is None:
        return

    lc = combine_dict(entry.data_ if isinstance(entry.data_, dict) else {}, cfg)
    negate = lc.get("low", False)
    t_on = lc.get("t_on", None)
    t_off = lc.get("t_off", None)
    state = entry.state

    with chip.line(line_num).open(direction=gpio.Direction.OUTPUT) as line:
        if mode == "write":
            await _with_output(link, line, src, _set_value, state, negate, subpath)
        elif mode == "oneshot":
            if t_on is None:
                logger.warning("t_on not set at %s", subpath)
                return
            await _with_output(link, line, src, _oneshot_value, state, negate, subpath, t_on)
        elif mode == "pulse":
            if t_on is None or t_off is None:
                logger.warning("t_on/t_off not set at %s", subpath)
                return
            await _with_output(link, line, src, _pulse_value, state, negate, subpath, t_on, t_off)
        else:
            logger.warning("Unknown output mode %r at %s", mode, subpath)


async def _with_output(
    link: LinkSender,
    line: Any,
    src: Path,
    proc: Any,
    *args: Any,
) -> None:
    """Watch a MoaT-Link source and call *proc* for each value change."""
    async with link.d_watch(src, mark=False, state=False) as wp:
        async for val in wp:
            if val is NotGiven:
                continue
            if val in (False, True, 0, 1):
                try:
                    await proc(link, line, bool(val), *args)
                except Exception as exc:
                    logger.warning("Output error at %s: %r", src, exc)
            else:
                logger.warning("Bad value %r at %s", val, src)


async def _set_value(
    link: LinkSender,
    line: Any,
    value: bool,
    state: Path | None,
    negate: bool,
) -> None:
    """Directly mirror a value to the GPIO line."""
    if negate:
        value = not value
    if line is not None:
        line.value = value != negate
    if state is not None:
        await link.d_set(state, value)


async def _oneshot_value(
    link: LinkSender,
    line: Any,
    val: bool,
    state: Path | None,
    negate: bool,
    t_on: float,
) -> None:
    """Pulse high for *t_on* seconds, then revert."""
    if val:
        await _set_value(link, line, True, state, negate)
        await anyio.sleep(t_on)
        await _set_value(link, line, False, state, negate)
    else:
        await _set_value(link, line, False, state, negate)


async def _pulse_value(
    link: LinkSender,
    line: Any,
    val: bool,
    state: Path | None,
    negate: bool,
    t_on: float,
    t_off: float,
) -> None:
    """Continuously pulse with duty cycle *t_on*/(*t_on*+*t_off*)."""
    if not val:
        await _set_value(link, line, False, state, negate)
        return
    if state is not None:
        await link.d_set(state, t_on / (t_on + t_off))
    while True:
        line.value = not negate
        await anyio.sleep(t_on)
        line.value = negate
        await anyio.sleep(t_off)
