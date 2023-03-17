from moat.micro.compat import Event

class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):
        return cls

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


class NoProxyError(ValueError):
    pass


class CancelledError(Exception):
    """
    Not an asyncio-style cancellation
    """
    pass

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

    event = None
    value = None

    def __init__(self, scope=None):
        self.event = Event()
        self.scope = scope

    def set(self, value):
        """Set the result to return this value, and wake any waiting task."""
        self.value = value
        self.event.set()

    def set_error(self, exc):
        """Set the result to raise this exceptio, and wake any waiting task."""
        if isinstance(exc, type):
            exc = exc()
        self.value = exc
        self.event.set()

    def is_set(self):
        """Check whether the event has occurred."""
        return self.value is not None

    def cancel(self):
        """Send a cancelation to the recipient.

        TODO: Trio can't do that cleanly.
        """
        if self.scope is not None:
            self.scope.cancel()
        self.set_error(CancelledError())

    async def wait(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value is not (yet) read; if it's an error, it will not be raised from here.
        """
        await self.event.wait()

    async def get(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value
