"""
This is a vendorized minimal version of the "outcome" package,
from https://pypi.org/project/outcome/.

Contrary to the upstream version, regular values (but not exceptions)
may be unwrapped more than once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["Error", "Outcome", "Value", "capture"]

T = TypeVar("T")


def capture(sync_fn: Callable[..., T], *args: Any, **kwargs: Any) -> Value[T] | Error:
    """Run ``sync_fn(*args, **kwargs)`` and capture the result."""
    try:
        return Value(sync_fn(*args, **kwargs))
    except Exception as exc:
        return Error(exc)


async def acapture(
    async_fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
) -> Value[T] | Error:
    """Run ``await async_fn(*args, **kwargs)`` and capture the result."""
    try:
        return Value(await async_fn(*args, **kwargs))
    except Exception as exc:
        return Error(exc)


class Outcome:
    """An abstract class representing the result of a Python computation."""


class Value(Outcome, Generic[T]):
    """Concrete :class:`Outcome` subclass representing a regular value."""

    def __init__(self, value: T) -> None:
        self.value: T = value

    def __repr__(self) -> str:
        return f"Value({self.value!r})"

    def unwrap(self) -> T:  # noqa: D102
        return self.value


class Error(Outcome):
    """Concrete :class:`Outcome` subclass representing a raised exception."""

    def __init__(self, error: Exception) -> None:
        self.error: Exception = error

    def __repr__(self) -> str:
        return f"Error({self.error!r})"

    def unwrap(self) -> None:  # noqa: D102
        captured_error = self.error
        try:
            raise captured_error
        finally:
            del captured_error, self
