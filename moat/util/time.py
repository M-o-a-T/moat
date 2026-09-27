"""Overridable wall-clock and monotonic time sources.

This module provides ``time()`` and ``monotonic()`` that normally delegate to
the standard-library functions of the same name, but whose backing functions
can be swapped at runtime via :func:`set_clock` / :func:`patch_clock`. Tests
and simulated runs thereby gain a controllable *wall* clock — the part that
:class:`trio.MockClock` (and anyio's clock) does *not* fake — without having
to thread a clock object through every caller.

For monotonic time consumed inside an event loop, prefer
:func:`loop_time`, which forwards to :func:`anyio.current_time` (already
fakeable via the runner's clock) and falls back to :func:`monotonic` only when
no loop is running. Keeping async monotonic readers on the event-loop clock
avoids maintaining two independent fake monotonic clocks.
"""

from __future__ import annotations

import anyio
import time as _time
from contextlib import contextmanager

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ["loop_time", "monotonic", "patch_clock", "set_clock", "time"]

# Sentinel distinguishing "argument omitted" from "explicitly passed None".
_UNSET: Any = object()

# Backing clock functions. Swapped by ``set_clock`` / ``patch_clock``.
_time_fn: Callable[[], float] = _time.time
_mono_fn: Callable[[], float] = _time.monotonic


def time() -> float:
    """Current wall-clock time, in seconds since the epoch."""
    return _time_fn()


def monotonic() -> float:
    """Current monotonic time, in seconds.

    Use this only from loop-less code. Inside an event loop, prefer
    :func:`loop_time` so the value tracks the (fakeable) loop clock.
    """
    return _mono_fn()


def loop_time() -> float:
    """Current monotonic time as seen by the running event loop.

    Delegates to :func:`anyio.current_time`; when no event loop is running
    (e.g. synchronous helper code invoked outside a runner), falls back to
    :func:`monotonic`.
    """
    try:
        return anyio.current_time()
    except RuntimeError:
        return _mono_fn()


def set_clock(
    *,
    time: Callable[[], float] | Any | None = _UNSET,
    monotonic: Callable[[], float] | Any | None = _UNSET,
) -> None:
    """Replace the backing clock functions.

    Only the slots for which an argument is *passed* are touched; omitted
    slots keep their current value. Passing ``None`` explicitly resets that
    slot to the corresponding standard-library function.

    Args:
        time: New wall-clock function, ``None`` to restore the default, or
            omit to leave it unchanged.
        monotonic: New monotonic-clock function, ``None`` to restore the
            default, or omit to leave it unchanged.
    """
    global _time_fn, _mono_fn
    if time is not _UNSET:
        _time_fn = _time.time if time is None else time
    if monotonic is not _UNSET:
        _mono_fn = _time.monotonic if monotonic is None else monotonic


@contextmanager
def patch_clock(
    *,
    time: Callable[[], float] | Any | None = _UNSET,
    monotonic: Callable[[], float] | Any | None = _UNSET,
) -> Iterator[None]:
    """Temporarily override the clock functions, restoring them on exit.

    Only the slots for which a non-default argument is supplied are changed;
    the others keep their current value. Prior slots are restored even when
    the body raises or the surrounding task is cancelled.

    Args:
        time: Temporary wall-clock function, ``None`` to force the default,
            or omit to leave it unchanged.
        monotonic: Temporary monotonic-clock function, ``None`` to force the
            default, or omit to leave it unchanged.
    """
    global _time_fn, _mono_fn
    old_time = _time_fn
    old_mono = _mono_fn
    try:
        set_clock(time=time, monotonic=monotonic)
        yield
    finally:
        _time_fn = old_time
        _mono_fn = old_mono
