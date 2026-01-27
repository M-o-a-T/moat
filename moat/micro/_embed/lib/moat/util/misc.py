"""
This module contains various helper functions and classes.
"""

from __future__ import annotations

from moat.lib.micro import (
    TimeoutError,  # pylint: disable=redefined-builtin # noqa:A004
    log,
    wait_for_ms,
)

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["wait_complain"]


class OutOfData(EOFError):
    pass


async def wait_complain(s: str, i: int, p: Callable, *a, **k):
    """
    Wait for a callable to complete, complaining if it takes too long.

    Args:
        s: Description string for logging.
        i: Timeout in milliseconds.
        p: Callable to wait for.
        *a: Positional arguments for the callable.
        **k: Keyword arguments for the callable.
    """
    try:
        await wait_for_ms(i, p, *a, **k)
    except TimeoutError:
        log("Delayed  %s", s)
        await p(*a, **k)
        log("Delay OK %s", s)
