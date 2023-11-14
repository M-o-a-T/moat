"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.util import NotGiven, ValueEvent, as_proxy
from moat.micro.compat import (
    TimeoutError,  # pylint: disable=redefined-builtin
    log,
    sleep_ms,
    ticks_add,
    ticks_diff,
    ticks_ms,
    wait_for_ms,
)
from moat.micro.proto.stack import RemoteError, SilentRemoteError

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from typing import Any, AsyncIterable, AsyncIterator, Callable, Iterator, Mapping

    from anyio import CancelScope

    from moat.micro.cmd.base import BaseCmd


StopIter = StopAsyncIteration

as_proxy("_KyErr", KeyError, replace=True)
as_proxy("_AtErr", AttributeError, replace=True)
as_proxy("_NiErr", NotImplementedError, replace=True)
as_proxy("_RemErr", RemoteError, replace=True)
as_proxy("_SRemErr", SilentRemoteError, replace=True)

as_proxy("_StpIter", StopIter, replace=True)


@as_proxy("_StpErr")
class StoppedError(Exception):
    "Called command/app is not running"


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

