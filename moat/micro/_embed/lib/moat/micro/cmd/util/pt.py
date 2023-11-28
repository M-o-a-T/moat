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


# like get/set_part but without the attributes


def get_p(cur, p, add=False):
    "retrieve an item"
    for pp in p:
        try:
            cur = cur[pp]
        except KeyError:
            if not add:
                raise
            cur[pp] = nc = {}
            cur = nc
    return cur


def set_p(cur, p, v):
    "set an item"
    cur = get_p(cur, p[:-1], add=True)
    cur[p[-1]] = v


def del_p(cur, p):
    "delete an item"
    pp = p[0]
    if pp in cur:
        if len(p) > 1:
            del_p(cur[pp], p[1:])
        if cur[pp]:
            return
        del cur[pp]
