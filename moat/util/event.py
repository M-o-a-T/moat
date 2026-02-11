"""
This module contains an awaitable value.
"""

from __future__ import annotations

import anyio
from concurrent.futures import CancelledError

import attr
import outcome

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from anyio.abc import CancelScope

__all__ = ["ValueEvent"]

T = TypeVar("T")


@attr.s
class ValueEvent:
    """A waitable value useful for inter-task synchronization,
    inspired by :class:`threading.Event`.

    An event object manages an internal value, which is initially
    unset, and a task can wait for it to become True.

    Args:
      ``scope``:  A cancelation scope that will be cancelled if/when
                  this ValueEvent is. Used for clean cancel propagation.

    Note that the value can only be read once.
    """

    event: anyio.Event = attr.ib(factory=anyio.Event, init=False)
    value: outcome.Value[Any] | outcome.Error | None = attr.ib(default=None, init=False)
    scope: CancelScope | None = attr.ib(default=None, init=True)

    def set(self, value: Any) -> None:
        """Set the result to return this value, and wake any waiting task."""
        self.value = outcome.Value(value)
        self.event.set()

    def set_error(self, exc: Exception) -> None:
        """Set the result to raise this exceptio, and wake any waiting task."""
        self.value = outcome.Error(exc)
        self.event.set()

    def is_set(self) -> bool:
        """Check whether the event has occurred."""
        return self.value is not None

    def cancel(self) -> None:
        """Send a cancelation to the recipient.

        TODO: Trio can't do that cleanly.
        """
        if self.scope is not None:
            self.scope.cancel()
        self.set_error(CancelledError())

    async def wait(self) -> None:
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value is not (yet) read; if it's an error, it will not be raised from here.
        """
        await self.event.wait()

    async def get(self) -> Any:
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        return self.value.unwrap()  # type: ignore[union-attr]  # value is set after wait
