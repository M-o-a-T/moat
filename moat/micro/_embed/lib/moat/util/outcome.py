from __future__ import annotations


def capture(sync_fn, *args, **kwargs):
    """Run ``sync_fn(*args, **kwargs)`` and capture the result."""
    try:
        return Value(sync_fn(*args, **kwargs))
    except Exception as exc:
        return Error(exc)


async def acapture(async_fn, *args, **kwargs):
    """Run ``await async_fn(*args, **kwargs)`` and capture the result."""
    try:
        return Value(await async_fn(*args, **kwargs))
    except Exception as exc:
        return Error(exc)


class Outcome:
    """An abstract class representing the result of a Python computation."""

    pass


class Value(Outcome):
    """Concrete :class:`Outcome` subclass representing a regular value."""

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Value({self.value!r})"

    def unwrap(self):
        return self.value


class Error(Outcome):
    """Concrete :class:`Outcome` subclass representing a raised exception."""

    def __init__(self, error):
        self.error = error

    def __repr__(self):
        return f"Error({self.error!r})"

    def unwrap(self):
        captured_error = self.error
        try:
            raise captured_error
        finally:
            del captured_error, self
