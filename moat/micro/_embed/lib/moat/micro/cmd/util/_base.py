"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util.compat import (
    TimeoutError,  # pylint: disable=redefined-builtin # noqa:A004
    log,
    wait_for_ms,
)

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Callable


async def wait_complain(s: str, i: int, p: Callable, *a, **k):
    "Complain on stderr if waiting too long"
    try:
        await wait_for_ms(i, p, *a, **k)
    except TimeoutError:
        log("Delayed  %s", s)
        await p(*a, **k)
        log("Delay OK %s", s)


async def run_no_exc(p, msg, x_err=()):
    """Call p(msg) but log exceptions"""
    try:
        r = p(**msg)
        if hasattr(r, "throw"):  # coroutine
            r = await r
    except x_err as err:
        log("Error in %r %r: %r", p, msg, err)
    except Exception as err:  # pylint:disable=broad-exception-caught
        log("Error in %r %r", p, msg, err=err)
