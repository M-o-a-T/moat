"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

from moat.lib.codec.errors import StoppedError

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from anyio import CancelScope

    from moat.micro.cmd.base import BaseCmd

    from collections.abc import Callable, Mapping
    from typing import Any


class ValueTask:
    """
    An object that forwards a task's return value.

    @i: seqnum
    @x: excluded errors
    @p: callable
    """

    def __init__(self, cmd: BaseCmd, i: int, x: list[Exception], p: Callable, *a, **k):
        self.cmd = cmd
        self.i = i
        self.p = p
        self.a: list[Any] = a
        self.k: Mapping[str, Any] = k
        self.x = x
        self._t: CancelScope = None

    async def start(self, tg):
        "Task starter. Called from the command."
        if self._t is not None:
            raise RuntimeError("dup")
        self._t = await tg.spawn(self._wrap, _name="Val")

    async def _wrap(self):
        try:
            err = None
            res = await self.p(*self.a, **self.k)
        except Exception as exc:  # pylint:disable=broad-exception-caught
            err = exc
        except BaseException as exc:  # pylint:disable=broad-exception-caught
            err = StoppedError(repr(exc))
        if err is None:
            await self.reply_result(res)
        else:
            await self.cmd.reply_error(self.i, err, self.x)
            if not isinstance(err, Exception):
                raise err

    async def reply_result(self, res):
        "forward the task's return value to the caller"
        await self.cmd.reply_result(self.i, res)

    def cancel(self):
        "cancel the iterator"
        if self._t is not None:
            self._t.cancel()
            self._t = False

    async def set_error(self, err):
        "tell the iterator to raise an error"
        self.cancel()
        await self.cmd.reply_error(self.i, err, self.x)
