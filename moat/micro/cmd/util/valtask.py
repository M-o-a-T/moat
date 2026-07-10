"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Protocol

    class HasValueTaskReplies(Protocol):
        """Required reply methods on command objects."""

        async def reply_error(self, i: int, err: Exception, x: list[Exception]) -> None:
            """Forward a task error."""

        async def reply_result(self, i: int, res: object) -> None:
            """Forward a task result."""

    class Cancellable(Protocol):
        """Cancel-capable task handle."""

        def cancel(self) -> None:
            """Cancel this task."""


class ValueTask:
    """
    An object that forwards a task's return value.

    @i: seqnum
    @x: excluded errors
    @p: callable
    """

    def __init__(
        self,
        cmd: HasValueTaskReplies,
        i: int,
        x: list[Exception],
        p: Callable[..., Awaitable[object]],
        *a: object,
        **k: object,
    ):
        self.cmd = cmd
        self.i = i
        self.p = p
        self.a = a
        self.k = k
        self.x = x
        self._t: Cancellable | None = None

    async def start(self, tg):
        "Task starter. Called from the command."
        if self._t is not None:
            raise RuntimeError("dup")
        self._t = await tg.spawn(self._wrap, _name="Val")

    async def _wrap(self):
        try:
            res = await self.p(*self.a, **self.k)
        except Exception as err:  # pylint:disable=broad-exception-caught
            await self.cmd.reply_error(self.i, err, self.x)
            return
        await self.reply_result(res)

    async def reply_result(self, res):
        "forward the task's return value to the caller"
        await self.cmd.reply_result(self.i, res)

    def cancel(self):
        "cancel the iterator"
        if self._t is not None:
            self._t.cancel()
            self._t = None

    async def set_error(self, err):
        "tell the iterator to raise an error"
        self.cancel()
        await self.cmd.reply_error(self.i, err, self.x)
